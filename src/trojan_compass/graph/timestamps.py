"""Source-review dates become explicit UTC date sentinels, never event times."""

from datetime import UTC, date, datetime, time


def source_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.utcoffset() is not None else None
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    if isinstance(value, str):
        try:
            # Neo4j imports persist SourceRecord.checked_at.isoformat(), a date string.
            reviewed = date.fromisoformat(value)
        except ValueError:
            try:
                timestamp = datetime.fromisoformat(value)
            except ValueError:
                return None
            return timestamp if timestamp.utcoffset() is not None else None
        return datetime.combine(reviewed, time.min, tzinfo=UTC)
    return None
