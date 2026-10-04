"""Pure transfer calculations without presentation dependencies; raw API dictionaries remain untouched."""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

Number = Union[int, float]
PartitionResult = Tuple[List[dict], List[dict]]

__all__ = [
    "Number", "PartitionResult", "known_nonnegative", "TransferProgress",
    "TransferSummary", "transfer_progress", "summarize_transfers", "partition_links",
]


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
        if self.loaded >= self.total:
            return 100.0
        # Float division may round near-complete large byte counts up to 100.
        return min(99.99999999999999, self.loaded / self.total * 100.0)

    @property
    def remaining(self) -> Optional[Number]:
        if self.loaded is None or self.total is None:
            return None
        return max(0, self.total - self.loaded)


def transfer_progress(link) -> TransferProgress:
    return TransferProgress(
        loaded=known_nonnegative(link.get("bytesLoaded")),
        total=known_nonnegative(link.get("bytesTotal")),
        speed=known_nonnegative(link.get("speed")),
        eta=known_nonnegative(link.get("eta")),
    )


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
    return TransferSummary(
        speed=_complete_sum(item.speed for item in progress),
        loaded=_complete_sum(item.loaded for item in progress),
        total=_complete_sum(item.total for item in progress),
        remaining=_complete_sum(item.remaining for item in progress),
    )


def partition_links(links) -> PartitionResult:
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
