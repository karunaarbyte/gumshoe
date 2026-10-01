"""One fixed timestamp format, so comparing the stored text orders by time."""

from datetime import UTC, datetime


def to_utc_iso(moment: datetime) -> str:
    """ISO-8601 in UTC with microseconds. A naive datetime is read as UTC."""
    moment = moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
    return moment.isoformat(timespec="microseconds")
