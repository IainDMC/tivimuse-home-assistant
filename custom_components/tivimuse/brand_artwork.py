"""Bundled TiviMuse artwork, served by Home Assistant's authenticated image proxy."""

from functools import cache
from pathlib import Path

APP_ICON_URL = "tivimuse://brand/app-icon-blue-square-v1"


@cache
def app_icon():
    """Read once in the executor; no remote image or guide request is needed."""
    return (Path(__file__).with_name("brand") / "icon.png").read_bytes(), "image/png"
