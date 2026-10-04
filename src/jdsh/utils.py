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


def human_percent(percent, precision=0):
    return "-" if percent is None else f"{percent:.{precision}f}%"
