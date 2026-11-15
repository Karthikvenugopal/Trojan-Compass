"""Apply education policy to model-classified data, never interpret student wording."""

from trojan_compass.contracts import RetrievalContext


def course_level_allowed(level: str, context: RetrievalContext) -> bool:
    if level not in {"graduate", "doctoral"}:
        return True
    if context.academic_level is not None:
        return context.academic_level.value in {"graduate", "doctoral"}
    # Unscoped catalog callers may browse all levels. Once a student's stage is
    # present, require a supported graduate classification for graduate results.
    scoped = context.study_stage is not None or any(
        a.field == "study_stage" and a.status != "not_answered" for a in context.answers
    )
    return not scoped
