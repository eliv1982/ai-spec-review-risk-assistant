from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Return the current UTC time as a canonical ISO 8601 string ending in 'Z'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
