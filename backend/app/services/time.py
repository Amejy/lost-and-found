from datetime import datetime, timezone


def as_naive_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def utcnow_naive():
    return datetime.utcnow()
