"""Validate editable values without interpreting paths on the client machine."""

from pathlib import PurePosixPath, PureWindowsPath
import unicodedata

PRIORITIES = ("HIGHEST", "HIGHER", "HIGH", "DEFAULT", "LOW", "LOWER", "LOWEST")


def priority_value(value):
    if not isinstance(value, str) or value.upper() not in PRIORITIES:
        raise ValueError("priority must be one of " + ", ".join(PRIORITIES))
    return value.upper()


def nonblank_text(value):
    if not isinstance(value, str) or not value.strip() or any(unicodedata.category(char) == "Cc" for char in value):
        raise ValueError("value must be nonempty text without control characters")
    return value


def rename_value(value, *, package=False):
    value = nonblank_text(value)
    if not package and (value in (".", "..") or "/" in value or "\\" in value):
        raise ValueError("link name must be a file name without path separators")
    return value


def directory_value(value):
    value = nonblank_text(value)
    if not (PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()):
        raise ValueError("directory must be an absolute path on the JDownloader machine")
    return value
