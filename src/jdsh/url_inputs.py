"""Collect add-command inputs without submitting links or writing to the terminal."""

from typing import Callable, Iterable, List, Optional

from . import clipboard
from .errors import JDShError


FileReader = Callable[[str], Iterable[str]]
ClipboardReader = Callable[[], Iterable[str]]


def _read_url_file(path: str) -> List[str]:
    with open(path, encoding="utf-8-sig") as url_file:
        return [line.strip() for line in url_file if line.strip()]


def collect_links(
    urls: Iterable[str], *, file_path: Optional[str] = None, use_clipboard: bool = False,
    read_file: Optional[FileReader] = None, read_clipboard: Optional[ClipboardReader] = None,
) -> List[str]:
    """Keep positional -> file -> clipboard order and existing input semantics.

    Positional arguments split on whitespace; file entries remain one per line.
    Only file/clipboard inputs enable ordered deduplication across all sources.
    Reader failures abort collection, even if an earlier source had valid URLs.
    """
    links = " ".join(urls).split()
    if file_path is not None:
        file_reader = _read_url_file if read_file is None else read_file
        try:
            links.extend(file_reader(file_path))
        except (OSError, UnicodeError) as e:
            raise JDShError(f"cannot read URL file {file_path!r}: {e}") from e

    if use_clipboard:
        clipboard_reader = clipboard.read_clipboard_links if read_clipboard is None else read_clipboard
        links.extend(clipboard_reader())

    if file_path is not None or use_clipboard:
        links = clipboard.dedupe_preserve_order(links)
    if not links:
        raise JDShError("no URLs to add")
    return links
