from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_settings


def local_now_naive() -> datetime:
    """Current wall-clock time in the configured ``APP_TIMEZONE``, returned naive.

    The DB's ``created_at`` is written by MySQL ``func.now()`` in the server's
    local timezone — verified Europe/Berlin (NOW() = UTC_TIMESTAMP() + 2h, CEST).
    Time-window cutoffs compared against ``created_at`` must be in that same
    wall-clock frame, not UTC, or they are off by the offset. If the DB server's
    timezone ever changes, set ``APP_TIMEZONE`` to match it.
    """
    return datetime.now(ZoneInfo(get_settings().APP_TIMEZONE)).replace(tzinfo=None)
