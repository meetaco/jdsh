import json
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from typing import Iterable, List, Optional


class ClipboardError(RuntimeError):
    """Raised when clipboard contents cannot be read or contain no links."""


class _HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: List[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.links.append(value)
                break

    # Be lenient if clipboard HTML contains the syntactic (though invalid) form <a .../>.
    def handle_startendtag(self, tag, attrs) -> None:
        self.handle_starttag(tag, attrs)


def dedupe_preserve_order(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def extract_links_from_html(html: str) -> List[str]:
    parser = _HrefParser()
    parser.feed(html)
    parser.close()
    return dedupe_preserve_order(parser.links)


def links_from_clipboard_data(html: Optional[str], plain_text: Optional[str]) -> List[str]:
    """Prefer anchor targets from HTML, falling back to whitespace-delimited text."""
    if html:
        links = extract_links_from_html(html)
        if links:
            return links

    if not plain_text:
        return []
    return dedupe_preserve_order(plain_text.split())


def _read_pasteboard_type(type_name: str) -> str:
    osascript = shutil.which("osascript")
    if not osascript:
        raise ClipboardError("failed to read macOS clipboard: osascript was not found")

    script = "\n".join(
        [
            "ObjC.import('AppKit');",
            "const pb = $.NSPasteboard.generalPasteboard;",
            f"const value = pb.stringForType({json.dumps(type_name)});",
            "value ? ObjC.unwrap(value) : '';",
        ]
    )
    completed = subprocess.run(
        [osascript, "-l", "JavaScript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"osascript exited with {completed.returncode}"
        raise ClipboardError(f"failed to read macOS clipboard: {detail}")
    return completed.stdout


def _read_plain_text() -> str:
    pasteboard_error = None
    try:
        text = _read_pasteboard_type("public.utf8-plain-text")
        if text:
            return text
    except ClipboardError as exc:
        pasteboard_error = exc

    pbpaste = shutil.which("pbpaste")
    if not pbpaste:
        if pasteboard_error:
            raise pasteboard_error
        return ""

    completed = subprocess.run(
        [pbpaste],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"pbpaste exited with {completed.returncode}"
        raise ClipboardError(f"failed to read macOS clipboard: {detail}") from pasteboard_error
    return completed.stdout


def read_clipboard_links() -> List[str]:
    if sys.platform != "darwin":
        raise ClipboardError("--clipboard is only supported on macOS")

    try:
        html = _read_pasteboard_type("public.html")
    except ClipboardError:
        html = None

    if html:
        links = extract_links_from_html(html)
        if links:
            return links

    plain_text = _read_plain_text()
    links = links_from_clipboard_data(None, plain_text)
    if not links:
        raise ClipboardError("clipboard does not contain HTML links or plain text")
    return links
