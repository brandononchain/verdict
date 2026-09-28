"""Conservative parsing of untrusted publication metadata."""
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime


def publication_date(value, captured_at):
    """Return an ISO date only when the provider value is plausible at capture."""
    if not isinstance(value, str) or len(value) > 80 or not value.strip():
        return ''
    try:
        raw = value.strip()
        if len(raw) == 10:
            published = date.fromisoformat(raw)
        else:
            try:
                moment = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            except ValueError:
                moment = parsedate_to_datetime(raw)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            published = moment.astimezone(timezone.utc).date()
        captured = datetime.fromtimestamp(captured_at, timezone.utc).date()
        if published > captured:
            return ''
        return published.isoformat()
    except (ValueError, TypeError, OverflowError):
        return ''
