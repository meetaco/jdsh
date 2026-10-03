"""Explicit settings loading; importing this module does not read config files."""

import configparser
import math
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Optional

from .errors import ConfigError

APP_KEY = "jd_shell_cli"

try:
    VERSION = version("jdsh")
except PackageNotFoundError:
    VERSION = "0.0.0"


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 3128
    refresh_rate: float = 1.0

    def __post_init__(self):
        if not self.host.strip():
            raise ConfigError("HOST must not be empty")
        if not 1 <= self.port <= 65535:
            raise ConfigError("PORT must be between 1 and 65535")
        if not math.isfinite(self.refresh_rate) or self.refresh_rate <= 0:
            raise ConfigError("REFRESH_RATE must be a finite positive number")


def load_settings(path: Optional[Path] = None) -> Settings:
    """Prefer jdsh.conf; use the documented jdsh.config alias if it is absent.

    Missing default files use defaults. An explicitly requested missing file,
    unreadable file or invalid preferred file is an error, without fallback.
    """
    if path is None:
        directory = Path.home() / ".config" / "jdsh"
        paths = [directory / "jdsh.conf", directory / "jdsh.config"]
    else:
        paths = [Path(path)]
    parser = configparser.ConfigParser()
    for candidate in paths:
        try:
            with candidate.open(encoding="utf-8-sig") as stream:
                parser.read_file(stream)
        except FileNotFoundError as e:
            if path is not None:
                raise ConfigError(f"Cannot read settings file {candidate}: {e}") from e
            continue
        except (OSError, UnicodeError, configparser.Error) as e:
            raise ConfigError(f"Cannot read settings file {candidate}: {e}") from e
        try:
            return Settings(
                host=parser.get("settings", "host", fallback="127.0.0.1").strip(),
                port=parser.getint("settings", "port", fallback=3128),
                refresh_rate=parser.getfloat("settings", "refresh_rate", fallback=1.0),
            )
        except (ValueError, configparser.Error, ConfigError) as e:
            raise ConfigError(f"Invalid settings in {candidate}: {e}") from e
    return Settings()
