"""Re-derive answers to known questions; defer unrelated turns to extraction.

Answers are copied verbatim only when they directly follow a recognized assistant
question. This does not infer skills, targets or other facts from free text.
"""

import re

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
            if field == "program" and re.fullmatch(r"[A-Za-z][A-Za-z &/().-]{1,99}", text):
                words = set(re.findall(r"[a-z]+", normalized))
                if (
                    not words
                    & {
                        "but",
                        "only",
                        "avoid",
                        "without",
                        "except",
                        "must",
                        "not",
                        "no",
                        "none",
                        "correction",
                        "actually",
                        "instead",
                        "how",
                        "why",
                        "what",
                    }
                    and text != "I haven't chosen a program"
                ):
                    # This records the literal answer to our program question, not
                    # inferred skills, a career target or completed coursework.
                    context.program = SupportedText(
                        value=text, evidence=[StudentStatement(message_index=index, quote=text)]
                    )
                    continue
            if field == "completed_courses":
                courses = text.removeprefix("I have completed these courses: ").rstrip(".")
                references = [part.strip() for part in courses.split(",")]
                if references and all(
                    re.fullmatch(r"[A-Za-z]{2,6}[ -]\d{3}[A-Za-z]{0,4}", part)
                    for part in references
                ):
                    context.completed_courses = [
                        SupportedText(
                            value=re.sub(r"[ -]", " ", part.upper()),
                            evidence=[StudentStatement(message_index=index, quote=text)],
                        )
                        for part in references
                    ]
                    continue  # Explicit completion answers do not establish skill mastery.

            # In offline demo mode, retain literal answers only when the immediately
            # preceding assistant turn asked for that specific information. This lets
            # students type a real answer instead of being trapped in the same prompt.
            evidence = [StudentStatement(message_index=index, quote=text)]
            if field in {"direction", "direction_detail"}:
                if normalized in STARTERS:
                    continue
                context.interests = [SupportedText(value=text, evidence=evidence)]
                continue
            if field == "study_stage":
                context.study_stage = SupportedText(value=text, evidence=evidence)
                continue
            if field == "work_experience":
                if normalized not in {"i have no experience", "no experience"}:
                    context.experiences = [SupportedText(value=text, evidence=evidence)]
                continue
            if field == "completed_courses":
                context.completed_courses = [SupportedText(value=text, evidence=evidence)]
                continue

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
