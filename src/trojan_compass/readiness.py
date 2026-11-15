"""Request-local answer states and readiness. No state survives a chat call."""

import re
from dataclasses import dataclass

from pydantic import BaseModel

from trojan_compass.contracts import (
    ChatMessage,
    Clarification,
    InformationField,
    InformationSnapshot,
    RetrievalContext,
    StudentAnswer,
    StudentStatement,
    SupportedText,
)

DIRECTION_QUESTION = "What interests you, or what would you like to explore?"
CHECKLIST_HINT = (
    "A direction and a little about your skills or experience help me find a useful fit. "
    "You can say you don't know or have none; I'll only ask extra questions when they matter."
)
LABELS = {
    "direction": "Interests or direction",
    "background": "Skills and experience",
    "program": "Program or major",
    "preferences": "Other preferences",
    "time_window": "Availability",
    "modality": "In person or online",
    "target": "Career direction to focus on",
}


def evidence_in(value: object) -> list[StudentStatement]:
    if isinstance(value, StudentStatement):
        return [value]
    if isinstance(value, BaseModel):
        return [e for name in type(value).model_fields for e in evidence_in(getattr(value, name))]
    if isinstance(value, list):
        return [e for item in value for e in evidence_in(item)]
    return []


def latest(answer: StudentAnswer) -> int:
    return max((e.message_index for e in answer.evidence), default=-1)


def derived_answers(context: RetrievalContext) -> dict[str, StudentAnswer]:
    groups: dict[str, tuple[list[str], object]] = {
        "direction": (
            [item.value for item in context.interests + context.goals]
            + ([context.target.name] if context.target else []),
            [*context.interests, *context.goals, context.target],
        ),
        "background": (
            [f"{s.name}: {s.status.replace('_', ' ')}" for s in context.skills]
            + [item.value for item in context.experiences + context.completed_courses],
            [*context.skills, *context.experiences, *context.completed_courses],
        ),
    }
    for name in ("time_window", "modality"):
        item = getattr(context.constraints, name)
        groups[name] = ([item.value] if item else [], item)
    groups["program"] = ([context.program.value] if context.program else [], context.program)
    preferences = context.constraints.additional_preferences
    groups["preferences"] = ([item.value for item in preferences], preferences)
    answers = {}
    for name, (values, source) in groups.items():
        evidence = sorted(evidence_in(source), key=lambda e: -e.message_index)[:8]
        answers[name] = StudentAnswer(
            field=name,
            status="provided" if values else "not_answered",
            # Display summary only; full facts/evidence remain intact for retrieval.
            value="; ".join(values)[:1000] if values else None,
            evidence=evidence,
        )
    for skill in context.skills:
        name = f"skills.{skill.name.casefold()}"
        answers[name] = StudentAnswer(
            field=name,
            # Unconfirmed mastery is unanswered until uncertainty is explicit.
            status="not_answered" if skill.status == "unknown" else "provided",
            value=None if skill.status == "unknown" else f"{skill.name}: {skill.status}",
            evidence=skill.evidence,
        )
    return answers


def question_field(text: str) -> str | None:
    """Recognize our questions for short replies; arbitrary assistant text proves nothing."""
    if text.startswith((DIRECTION_QUESTION, "Which topic would you like to explore?")):
        return "direction"
    if text.startswith("When would you be available?"):
        return "time_window"
    if text.startswith("Would you prefer in-person or online options?"):
        return "modality"
    if text.startswith("What skills, projects or courses have you tried so far?"):
        return "background"
    match = re.match(r"^How comfortable are you with (.+)\?", text)
    if match:
        return f"skills.{match[1].casefold()}"
    if text.startswith(
        (
            "What kind of work at ",
            "A few things in the graph match ",
            "Which kind of work there interests you?",
        )
    ):
        return "target"
    return None


def explicit_short_answers(messages: list[ChatMessage]) -> list[StudentAnswer]:
    answers = []
    for index, message in enumerate(messages):
        if message.role != "user" or index == 0 or messages[index - 1].role != "assistant":
            continue
        field = question_field(messages[index - 1].content)
        text = message.content.casefold().replace("’", "'").strip(" .!")
        if not field:
            continue
        unknown = text in {
            "i'm not sure",
            "i am not sure",
            "i don't know",
            "i don't know yet",
            "not sure",
            "i'd rather not say",
            "skip this question",
        }
        none = text in {"none", "no preference", "no preferences", "no direction yet"}
        if field == "background" and text in {"i have no experience", "no experience"}:
            none = True
        if unknown or none:
            answers.append(
                StudentAnswer(
                    field=field,
                    status="unknown" if unknown else "none",
                    evidence=[StudentStatement(message_index=index, quote=message.content)],
                )
            )
    return answers


def clear_field(context: RetrievalContext, field: str) -> None:
    if field == "direction":
        context.interests = []
        context.goals = []
        context.target = None
    elif field == "background":
        context.skills = []
        context.experiences = []
        context.completed_courses = []
    elif field in ("time_window", "modality"):
        setattr(context.constraints, field, None)
    elif field == "program":
        context.program = None
    elif field == "preferences":
        context.constraints.additional_preferences = []
    # A target clarification narrows an existing company/role. No preference
    # between its directions does not retract that original target.
    elif field.startswith("skills."):
        context.skills = [s for s in context.skills if s.name.casefold() != field[7:]]


def prune_before_edit(context: RetrievalContext, field: str, boundary: int) -> None:
    """An edit replaces older facts even if extraction also returned a newer fact.

    Filtering individual evidence prevents a new interest from accidentally keeping
    an older career target alive. Facts from later natural corrections survive.
    """

    def current(value: object) -> bool:
        return max((e.message_index for e in evidence_in(value)), default=-1) >= boundary

    related = {field}
    if field == "direction":
        context.interests = [v for v in context.interests if current(v)]
        context.goals = [v for v in context.goals if current(v)]
        if context.target and not current(context.target):
            context.target = None
        related.add("target")
    elif field == "background":
        context.skills = [v for v in context.skills if current(v)]
        context.experiences = [v for v in context.experiences if current(v)]
        context.completed_courses = [v for v in context.completed_courses if current(v)]
        related.update(a.field for a in context.answers if a.field.startswith("skills."))
    elif field == "target":
        if context.target and not current(context.target):
            context.target = None
        context.goals = [v for v in context.goals if current(v)]
    elif field in ("time_window", "modality"):
        if not current(getattr(context.constraints, field)):
            setattr(context.constraints, field, None)
    elif field == "program":
        if not current(context.program):
            context.program = None
    elif field == "preferences":
        context.constraints.additional_preferences = [
            v for v in context.constraints.additional_preferences if current(v)
        ]
    elif field.startswith("skills."):
        context.skills = [v for v in context.skills if v.name.casefold() != field[7:] or current(v)]
    context.answers = [
        a for a in context.answers if a.field not in related or latest(a) >= boundary
    ]


@dataclass
class RequestInformation:
    context: RetrievalContext
    answers: dict[str, StudentAnswer]
    required: list[str]

    def require(self, field: str) -> None:
        if field not in self.required:
            self.required.append(field)

    def answer(self, field: str) -> StudentAnswer:
        return self.answers.get(field, StudentAnswer(field=field, status="not_answered"))

    def snapshot(self) -> InformationSnapshot:
        # Keep optional fields out of the checklist until supplied or material.
        supplied_constraints = [
            key
            for key in ("time_window", "modality", "program", "preferences")
            if self.answer(key).status != "not_answered"
        ]
        keys = list(
            dict.fromkeys(["direction", "background", *self.required, *supplied_constraints])
        )
        missing = [key for key in self.required if self.answer(key).status == "not_answered"]
        return InformationSnapshot(
            ready=not missing,
            missing_fields=missing,
            fields=[
                InformationField(
                    **self.answer(key).model_dump(exclude={"evidence"}),
                    label=LABELS.get(key, f"Comfort with {key[7:]}"),
                    category="fixed" if key in ("direction", "background") else "request",
                    required=key in self.required,
                )
                for key in keys
            ],
        )

    def missing_question(self) -> Clarification | None:
        missing = self.snapshot().missing_fields
        if not missing:
            return None
        field = missing[0]
        questions = {
            "background": (
                "What skills, projects or courses have you tried so far?",
                ["I have no experience", "I don't know"],
            ),
            "direction": (
                DIRECTION_QUESTION,
                ["Building things", "Understanding people", "I don't know"],
            ),
            "time_window": (
                "When would you be available?",
                ["This week", "This semester", "I don't know"],
            ),
            "modality": (
                "Would you prefer in-person or online options?",
                ["In person", "Online", "No preference"],
            ),
        }
        text, options = questions[field]
        return Clarification(
            text=text,
            options=options,
            requested_fields=[field],
            reason="This answer materially affects which options fit the current request.",
        )


def request_information(
    context: RetrievalContext, messages: list[ChatMessage]
) -> RequestInformation:
    """Rebuild answers from evidence and explicit edits, including clearing old facts."""
    context = context.model_copy(deep=True)
    for index, message in enumerate(messages):
        if message.edit:
            # Unknown target refinement keeps the existing company; a provided
            # replacement must not retain the previous target.
            if message.edit.field == "target" and message.edit.status != "provided":
                continue
            boundary = index if message.edit.status == "provided" else index + 1
            prune_before_edit(context, message.edit.field, boundary)
    answers = derived_answers(context)
    explicit = [*context.answers, *explicit_short_answers(messages)]
    for index, message in enumerate(messages):
        if message.edit:
            explicit.append(
                StudentAnswer(
                    **message.edit.model_dump(),
                    evidence=[StudentStatement(message_index=index, quote=message.content)],
                )
            )
    # Apply in conversation order. A later natural correction beats an older panel edit.
    for answer in sorted(explicit, key=latest):
        old = answers.get(answer.field)
        if old is not None and latest(old) > latest(answer):
            continue
        answers[answer.field] = answer
        if answer.status != "provided":
            clear_field(context, answer.field)
            prefixes = ("target",) if answer.field == "direction" else ()
            if answer.field == "background":
                prefixes = ("skills.",)
            for key in list(answers):
                if key != answer.field and any(key.startswith(p) for p in prefixes):
                    if latest(answers[key]) <= latest(answer):
                        del answers[key]
        elif answer.value is not None and (old is None or latest(old) < latest(answer)):
            # Retain only facts extracted at/after the correction. If extraction omitted
            # the edit, its literal sentence can still be searched without invented skills.
            clear_field(context, answer.field)
            supported = SupportedText(value=answer.value, evidence=answer.evidence)
            if answer.field == "direction":
                context.interests = [supported]
            elif answer.field == "target" and context.target is None:
                context.interests.append(supported)
                answers["direction"] = StudentAnswer(
                    field="direction",
                    status="provided",
                    value=answer.value,
                    evidence=answer.evidence,
                )
            elif answer.field == "background":
                context.experiences = [supported]
            elif answer.field in ("time_window", "modality"):
                setattr(context.constraints, answer.field, supported)
            elif answer.field == "program":
                context.program = supported
            elif answer.field == "preferences":
                context.constraints.additional_preferences = [supported]
    context.answers = list(answers.values())
    required = ["direction", *(r.field for r in context.requested_context)]
    return RequestInformation(context, answers, list(dict.fromkeys(required)))


def retrieval_query(messages: list[ChatMessage]) -> str:
    """Keep the student's search preference while they answer questions or edit facts."""
    user_turns = [message for message in messages if message.role == "user" and not message.edit]
    for message in reversed(user_turns):
        if re.search(
            r"\b(courses?|classes|events?|workshops?|meetups?|talks?|panels?|hackathons?)\b",
            message.content,
            re.I,
        ):
            return message.content
    return user_turns[-1].content if user_turns else messages[-1].content
