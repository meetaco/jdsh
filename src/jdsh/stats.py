"""Pure transfer calculations; raw API dictionaries remain untouched."""

import math
from dataclasses import dataclass
from typing import Optional, Union

Number = Union[int, float]


def known_nonnegative(value) -> Optional[Number]:
    """Missing, negative sentinel, nonnumeric and nonfinite values are unknown."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return value


@dataclass(frozen=True)
class TransferProgress:
    loaded: Optional[Number]
    total: Optional[Number]
    speed: Optional[Number]
    eta: Optional[Number]

    @property
    def percent(self) -> Optional[float]:
        if self.loaded is None or self.total is None or self.total == 0:
            return None
        return 100.0 if self.loaded >= self.total else self.loaded / self.total * 100.0

    @property
    def remaining(self) -> Optional[Number]:
        if self.loaded is None or self.total is None:
            return None
        return max(0, self.total - self.loaded)


def transfer_progress(link) -> TransferProgress:
    return TransferProgress(*(known_nonnegative(link.get(key)) for key in
                              ("bytesLoaded", "bytesTotal", "speed", "eta")))


@dataclass(frozen=True)
class TransferSummary:
    speed: Optional[Number]
    loaded: Optional[Number]
    total: Optional[Number]
    remaining: Optional[Number]


def _complete_sum(values) -> Optional[Number]:
    values = list(values)
    return None if any(value is None for value in values) else known_nonnegative(sum(values))


def summarize_transfers(links) -> TransferSummary:
    """Unknown values make their aggregate unknown, rather than a partial total."""
    progress = [transfer_progress(link) for link in links]
    return TransferSummary(*(_complete_sum(getattr(item, field) for item in progress)
                             for field in ("speed", "loaded", "total", "remaining")))


def partition_links(links):
    """Preserve API flags and original dictionaries; finished links are excluded."""
    running, unfinished = [], []
    for link in links:
        if link.get("finished"):
            continue
        if link.get("running"):
            running.append(link)
        elif link.get("enabled"):
            unfinished.append(link)
    return running, unfinished
