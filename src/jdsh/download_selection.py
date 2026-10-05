"""Explicit link/package selections shared by download commands and services."""

from dataclasses import dataclass
from typing import Iterable, Tuple

MAX_DOWNLOAD_ID = (1 << 63) - 1
SELECTED_COMMANDS = ("enable", "disable", "resume", "force", "remove", "rm")


def download_id(value):
    """Accept positive IDs representable by JDownloader's signed long type."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("download IDs must be positive integers")
    try:
        result = int(value)
    except ValueError as error:
        raise ValueError("download IDs must be positive integers") from error
    if not 0 < result <= MAX_DOWNLOAD_ID:
        raise ValueError("download IDs must be between 1 and 9223372036854775807")
    return result


@dataclass(frozen=True)
class DownloadSelection:
    link_ids: Tuple[int, ...]
    package_ids: Tuple[int, ...]


def select_downloads(link_ids: Iterable = (), package_ids: Iterable = ()) -> DownloadSelection:
    """Validate and deduplicate each namespace in order; never default to all."""
    links = tuple(dict.fromkeys(download_id(value) for value in link_ids))
    packages = tuple(dict.fromkeys(download_id(value) for value in package_ids))
    if not links and not packages:
        raise ValueError("at least one download link ID or package ID is required")
    return DownloadSelection(links, packages)
