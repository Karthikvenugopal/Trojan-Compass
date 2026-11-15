"""Local provider transport uses synthetic JSON; no inference/server access is required."""

import json

import httpx
import pytest
from pydantic import BaseModel

from trojan_compass.api import configured_extractor
from trojan_compass.failures import FailureReason
from trojan_compass.llm import LLMFailure, configured_llm
from trojan_compass.ollama import OllamaContextExtractor, OllamaStructuredLLM


class Result(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_local_schema_generation_has_no_credentials_threads_or_retained_session() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            assert json.loads(request.content) == {"model": "qwen3:4b"}
            return httpx.Response(200, json={"model_info": {"qwen3.context_length": 40960}})
        calls.append(request)
        assert request.url.host == "127.0.0.1" and request.url.path == "/api/chat"
        assert "authorization" not in request.headers and "cookie" not in request.headers
        payload = json.loads(request.content)
        assert payload["format"] == Result.model_json_schema()
        assert payload["stream"] is False and payload["keep_alive"] == 0
        assert payload["think"] is False
        assert 4096 <= payload["options"]["num_ctx"] < 32768
        assert payload["options"]["num_ctx"] >= 1024 + payload["options"]["num_predict"]
        assert not {"context", "tools", "previous_response_id", "thread", "store"} & set(payload)
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": '{"answer":"Synthetic local reply"}'},
                "done": True,
                "done_reason": "stop",
            },
        )

    llm = OllamaStructuredLLM("qwen3:4b", transport=httpx.MockTransport(handler))
    result = await llm.complete("Use the schema", "Synthetic request", Result)
    assert result.answer == "Synthetic local reply" and len(calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com",
        "http://example.invalid:11434",
        "http://127.0.0.1:11434/private",
        "http://user:password@127.0.0.1:11434",
        "http://127.0.0.1:11434?key=secret",
    ],
)
def test_local_endpoint_cannot_be_reconfigured_to_cloud_or_arbitrary_paths(url: str) -> None:
    with pytest.raises(ValueError):
        OllamaStructuredLLM("qwen3:4b", base_url=url)


@pytest.mark.parametrize("model", ["glm-5:cloud", "qwen3-cloud", "", "../cloud/model"])
def test_cloud_model_tags_are_rejected(model: str) -> None:
    with pytest.raises(ValueError):
        OllamaStructuredLLM(model)


@pytest.mark.asyncio
async def test_local_failure_never_falls_back_to_an_external_provider() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, json={"error": "PRIVATE"})

    with pytest.raises(LLMFailure) as caught:
        await OllamaStructuredLLM("qwen3:4b", transport=httpx.MockTransport(handler)).complete(
            "S", "U", Result
        )
    assert caught.value.reason == FailureReason.PROVIDER and str(caught.value) == ""
    assert len(calls) == 1 and calls[0].url.host == "127.0.0.1"


@pytest.mark.asyncio
async def test_oversized_local_context_is_rejected_without_truncation_or_sending() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise AssertionError("Input must not be silently truncated and sent")

    with pytest.raises(LLMFailure) as caught:
        await OllamaStructuredLLM(
            "qwen3:4b", context_length=8192, transport=httpx.MockTransport(handler)
        ).complete("S", "x" * 8192, Result)
    assert caught.value.reason == FailureReason.LOCAL_CONTEXT and not calls


def test_local_provider_configuration_requires_no_cloud_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:4b")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert isinstance(configured_llm(), OllamaStructuredLLM)
    assert isinstance(configured_extractor(), OllamaContextExtractor)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {"remote_model": "remote-ai", "remote_host": "https://ollama.com"},
        {"model_info": {"qwen3.context_length": 4096}},
    ],
)
async def test_cloud_alias_or_small_model_window_is_rejected_before_any_student_content(
    metadata: dict[str, object],
) -> None:
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert json.loads(request.content) == {"model": "qwen3:4b"}
        return httpx.Response(200, json=metadata)

    with pytest.raises(LLMFailure):
        await OllamaStructuredLLM("qwen3:4b", transport=httpx.MockTransport(handler)).complete(
            "S", "Synthetic private input", Result
        )
    assert paths == ["/api/show"]
