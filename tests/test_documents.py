"""Only synthetic documents, created in memory; no student content or provider calls."""

import importlib.util
import io
import logging
import zipfile

import pytest
from fastapi.testclient import TestClient

from trojan_compass.api import create_app
from trojan_compass.document_worker import extract
from trojan_compass.documents import MAX_DOCUMENT_BYTES, DocumentFailure, MemoryDocumentParser


def docx(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
            + text
            + "</w:t></w:r></w:p></w:body></w:document>",
        )
    return buffer.getvalue()


async def test_docx_worker_and_api_parse_in_memory_without_content_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    content = docx("Synthetic private marker: I volunteered in a research project.")
    result = await MemoryDocumentParser().parse(content, "docx")
    assert result.text.startswith("Synthetic private marker")
    with caplog.at_level(logging.DEBUG), TestClient(create_app()) as client:
        response = client.post(
            "/api/import-document?format=docx",
            content=content,
            headers={"Content-Type": "application/octet-stream"},
        )
    assert response.status_code == 200
    assert response.json()["text"] == result.text
    assert response.headers["cache-control"] == "no-store"
    assert "Synthetic private marker" not in caplog.text


@pytest.mark.parametrize("content", [b"not a document", docx(""), docx("x" * 20001)])
async def test_unreadable_or_oversized_text_has_a_sanitized_failure(content: bytes) -> None:
    with pytest.raises(DocumentFailure):
        await MemoryDocumentParser().parse(content, "docx")


def test_xml_entities_and_zip_expansion_are_rejected() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "x" * (13 * 1024 * 1024))
    with pytest.raises(ValueError):
        extract(buffer.getvalue(), "docx")
    entity = io.BytesIO()
    with zipfile.ZipFile(entity, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]><x>&secret;</x>',
        )
    with pytest.raises(ValueError):
        extract(entity.getvalue(), "docx")


def test_binary_upload_limit_and_invalid_format_do_not_echo_input() -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/import-document?format=docx", content=b"x" * (MAX_DOCUMENT_BYTES + 1)
        )
        invalid = client.post(
            "/api/import-document?format=private-marker", content=b"Synthetic private marker"
        )
    assert response.status_code == 413 and "4194304" in response.text
    assert invalid.status_code == 422 and "private-marker" not in invalid.text


def synthetic_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    raw = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(raw))
        raw.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(raw)
    raw.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets:
        raw.extend(f"{offset:010d} 00000 n \n".encode())
    raw.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    return bytes(raw)


@pytest.mark.skipif(
    importlib.util.find_spec("pypdf") is None, reason="PDF dependency is installed in full CI"
)
async def test_real_pdf_reader_and_worker_accept_text_pdf() -> None:
    content = synthetic_pdf("Synthetic student knows research methods.")
    assert "research methods" in extract(content, "pdf")
    result = await MemoryDocumentParser().parse(content, "pdf")
    assert "research methods" in result.text and result.kind == "pdf"


async def test_cancelled_parser_kills_and_awaits_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from typing import Any

    started = asyncio.Event()

    class Worker:
        returncode: int | None = None
        waited = False
        killed = False

        async def communicate(self, content: bytes) -> tuple[bytes, bytes]:
            started.set()
            await asyncio.Event().wait()
            return b"", b""

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        async def wait(self) -> int:
            self.waited = True
            return self.returncode or 0

    worker = Worker()

    async def launch(*args: Any, **kwargs: Any) -> Worker:
        return worker

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    task = asyncio.create_task(MemoryDocumentParser().parse(docx("Synthetic"), "docx"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert worker.killed and worker.waited


def test_full_background_does_not_overflow_search_query_or_replace_explicit_intent() -> None:
    from trojan_compass.contracts import ChatMessage, RecommendationRequest, RetrievalContext
    from trojan_compass.services import latest_search_query

    background = ChatMessage(role="user", content="Use my resume as background.\n" + "x" * 20000)
    query = latest_search_query([background])
    request = RecommendationRequest(context=RetrievalContext(), user_query=query)
    assert request.user_query == "Use my resume as background."
    actual = ChatMessage(role="user", content="Find design courses")
    assert latest_search_query([actual, background]) == actual.content
    assert len(background.content) > 20000  # Nothing in the active conversation was truncated.
