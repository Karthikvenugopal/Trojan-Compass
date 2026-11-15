"""Full HTTP journeys against the actual USC seed and recommendation engine.

Only language extraction is faked. These catch suggested choices that cannot
progress through real data, which isolated orchestration fakes cannot detect.
"""

from fastapi.testclient import TestClient

from trojan_compass.composition import RuntimeSettings, create_configured_app
from trojan_compass.contracts import (
    ChatMessage,
    ChatResponse,
    RetrievalContext,
    StudentStatement,
    SupportedText,
)


class JourneyExtractor:
    async def extract(self, messages: list[ChatMessage]) -> RetrievalContext:
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if message.role != "user":
                continue
            text = message.content
            if text == "Building things":
                return RetrievalContext(
                    interests=[
                        SupportedText(
                            value=text, evidence=[StudentStatement(message_index=index, quote=text)]
                        )
                    ]
                )
            if text in (
                "Programming (apps or websites)",
                "Computer programming",
                "Coding",
                "Computer programming. I have no experience.",
            ):
                return RetrievalContext(
                    interests=[
                        SupportedText(
                            value="programming",
                            evidence=[StudentStatement(message_index=index, quote=text)],
                        )
                    ]
                )
            if text == "Marine biology":
                return RetrievalContext(
                    interests=[
                        SupportedText(
                            value=text, evidence=[StudentStatement(message_index=index, quote=text)]
                        )
                    ]
                )
        return RetrievalContext()


def send(client: TestClient, history: list[dict[str, str]], text: str) -> ChatResponse:
    history.append({"role": "user", "content": text})
    response = client.post("/api/chat", json={"messages": history})
    assert response.status_code == 200
    data = ChatResponse.model_validate(response.json())
    history.append({"role": "assistant", "content": data.message})
    return data


def test_beginner_can_follow_choices_to_a_sourced_course_without_a_career_goal() -> None:
    app = create_configured_app(RuntimeSettings(mode="campus"), extractor=JourneyExtractor())
    history: list[dict[str, str]] = []
    with TestClient(app) as client:
        first = send(client, history, "I'm not sure where to start.")
        assert first.recommendations == []
        assert "Building things" in first.suggested_replies
        second = send(client, history, "Building things")
        assert second.recommendations == []
        assert second.message == "What kind of things would you enjoy building?"
        assert "Programming (apps or websites)" in second.suggested_replies
        assert second.limitations == []
        third = send(client, history, "Programming (apps or websites)")
        assert third.recommendations == []
        assert third.information.missing_fields == ["background"]
        result = send(client, history, "I have no experience")
        assert result.recommendations
        assert result.information.ready
        assert any(rec.id == "usc-course-csci-103l" for rec in result.recommendations)
        assert all(rec.kind == "course" for rec in result.recommendations)
        for rec in result.recommendations:
            assert rec.sources
            assert any("Skill:" in step for step in rec.evidence_path)
            assert "Software developer" not in " ".join(rec.evidence_path)
            assert "you know" not in " ".join(rec.why_relevant).casefold()


def test_unsure_about_refinement_gets_labeled_general_options_without_repeating() -> None:
    app = create_configured_app(RuntimeSettings(mode="campus"), extractor=JourneyExtractor())
    history: list[dict[str, str]] = []
    with TestClient(app) as client:
        send(client, history, "Building things")
        background = send(client, history, "I don't know")
        assert background.information.missing_fields == ["background"]
        result = send(client, history, "I have no experience")
        assert "general campus starting points" in result.message
        assert result.recommendations
        assert result.suggested_replies == []


def test_missing_data_is_explained_once_with_working_sourced_alternatives() -> None:
    app = create_configured_app(RuntimeSettings(mode="campus"), extractor=JourneyExtractor())
    history: list[dict[str, str]] = []
    with TestClient(app) as client:
        question = send(client, history, "Marine biology")
        assert question.information.missing_fields == ["background"]
        result = send(client, history, "I have no experience")
        assert result.recommendations == []
        assert "current data" in result.message
        assert result.limitations == []
        assert "Computer programming" in result.suggested_replies
        narrowed = send(client, history, "Computer programming")
        assert narrowed.recommendations


def test_both_minimum_answers_can_be_given_in_the_first_message() -> None:
    app = create_configured_app(RuntimeSettings(mode="campus"), extractor=JourneyExtractor())
    with TestClient(app) as client:
        response = send(client, [], "Computer programming. I have no experience.")
        assert response.information.ready
        assert response.recommendations
        assert response.suggested_replies == []
