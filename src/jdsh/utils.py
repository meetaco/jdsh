from datetime import datetime
from typing import Optional

from .stats import Number, known_nonnegative


def human_size(bytes_val: Optional[Number]) -> str:
    bytes_val = known_nonnegative(bytes_val)
    if bytes_val is None:
        return "null"
    if bytes_val == 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_val < 1024:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.2f} TB"

def human_eta(seconds: Optional[Number]) -> str:
    """Preserve the existing dash for zero or unknown ETA; bytes retain zero."""
    seconds = known_nonnegative(seconds)
    if seconds is None or seconds == 0:
        return "-"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def human_percent(percent: Optional[float], precision: int = 0) -> str:
    if percent is None:
        return "-"
    if percent < 100:
        percent = min(percent, 100 - 10 ** -precision)
    return f"{percent:.{precision}f}%"


def human_timestamp(timestamp: Optional[Number]) -> str:
    """Format JD's epoch milliseconds in local time, including its UTC offset."""
    timestamp = known_nonnegative(timestamp)
    if timestamp is None or timestamp == 0:
        return "-"
    try:
        date = datetime.fromtimestamp(timestamp / 1000).astimezone()
    except (OverflowError, OSError, ValueError):
        return "-"
    return date.isoformat(sep=" ", timespec="seconds")
