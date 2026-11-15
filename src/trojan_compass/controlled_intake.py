"""Re-derive only explicit UI selections; defer every unsupported turn to extraction.

This is production intake, not fixture data or a fallback recommendation generator.
No earlier free-form message, correction or constraint can be skipped to use it.
"""

from trojan_compass.contracts import ChatMessage, RetrievalContext, StudentStatement, SupportedText
from trojan_compass.readiness import DETAIL_QUESTIONS, question_field

STARTERS = frozenset(
    {
        "hi",
        "hello",
        "help me get started",
        "i'm not sure where to start",
        "i am not sure where to start",
        "i have an interest to explore",
        "i know what i want to do",
    }
)
DIRECTIONS = frozenset(
    {
        "Arts or storytelling",
        "Understanding people",
        "Building things",
        "Business or public service",
        "I don't know",
    }
)
UNCERTAIN = frozenset({"i don't know", "i'm not sure", "i am not sure", "none", "no preference"})


class ControlledIntakeParser:
    """Stateless closed-choice parser. None means the entire conversation needs the LLM."""

    def parse(self, messages: list[ChatMessage]) -> RetrievalContext | None:
        context = RetrievalContext()
        details = {option for _, options in DETAIL_QUESTIONS.values() for option in options}
        for index, message in enumerate(messages):
            if message.role != "user":
                continue
            text = message.content.strip()
            normalized = text.casefold().replace("’", "'").strip(" .!")
            if message.edit is not None:
                # Typed panel edits are applied by readiness, including corrections.
                edit = message.edit
                label, separator, answer = text.partition(": ")
                expected = (
                    edit.value
                    if edit.status == "provided"
                    else {
                        "unknown": "I don’t know",
                        "none": "None",
                        "not_answered": "Not answered",
                    }[edit.status]
                )
                if not (label.startswith("Update my ") and separator and answer == expected):
                    return None
                if edit.status == "provided":
                    if edit.field.startswith("skills."):
                        name = edit.field[7:]
                        if (edit.value or "").casefold() not in {
                            f"i am comfortable with {name}.",
                            f"i am learning {name}.",
                            f"i have not learned {name} yet.",
                        }:
                            return None
                    elif edit.field not in {
                        "direction",
                        "direction_detail",
                        "program",
                        "study_stage",
                        "target",
                    }:
                        return None
                    # Keep compound/free-form constraints on the structured LLM path.
                    elif len(edit.value or "") > 100 or any(
                        word in (edit.value or "").casefold().split()
                        for word in (
                            "only",
                            "but",
                            "avoid",
                            "without",
                            "except",
                            "must",
                            "don't",
                            "not",
                        )
                    ):
                        return None
                continue
            if index == 0 and normalized in STARTERS:
                continue  # A greeting proves no student facts.
            previous = messages[index - 1] if index else None
            field = (
                question_field(previous.content)
                if previous and previous.role == "assistant"
                else None
            )
            if field is None:
                return None
            if normalized in UNCERTAIN:
                continue  # Readiness scopes explicit unknown/none to the question.
            allowed = (
                field == "direction"
                and text in DIRECTIONS
                or field == "direction_detail"
                and text in details
                or field == "study_stage"
                and text in {"Not started at USC yet", "Undergraduate", "Graduate student"}
                or field == "program"
                and text == "I haven't chosen a program"
                or field in {"work_experience", "background"}
                and text == "I have no experience"
            )
            if not allowed:
                return None
            if field in {"direction", "direction_detail"}:
                context.interests = [
                    SupportedText(
                        value=text, evidence=[StudentStatement(message_index=index, quote=text)]
                    )
                ]
        return context
