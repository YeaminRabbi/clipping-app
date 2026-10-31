"""Caption style templates. Sizes are in pixels for a 1920-pixel-tall frame and scale with the output."""

import os
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

REFERENCE_HEIGHT = 1920


@dataclass(frozen=True)
class CaptionStyle:
    template: str
    font: str
    size: int  # px at REFERENCE_HEIGHT
    bold: bool
    uppercase: bool
    color: str  # "#RRGGBB"
    highlight: str  # colour of the word being spoken ("" = no highlight)
    outline: int  # px at REFERENCE_HEIGHT
    box: bool  # opaque box behind the text instead of an outline
    position: str  # top | middle | bottom
    max_words: int  # per cue
    max_chars: int  # per line
    max_lines: int
    effect: str  # none | pop (active word scales up) | karaoke (words fill as spoken)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


TEMPLATES: dict[str, CaptionStyle] = {
    "bold_pop": CaptionStyle(
        template="bold_pop", font="Arial Black", size=88, bold=True, uppercase=True, color="#FFFFFF",
        highlight="#FFE600", outline=7, box=False, position="middle", max_words=3, max_chars=16, max_lines=2,
        effect="pop",
    ),
    "karaoke": CaptionStyle(
        template="karaoke", font="Segoe UI Black", size=72, bold=True, uppercase=False, color="#FFFFFF",
        highlight="#22D3EE", outline=5, box=False, position="bottom", max_words=7, max_chars=22, max_lines=2,
        effect="karaoke",
    ),
    "classic": CaptionStyle(
        template="classic", font="Arial", size=60, bold=True, uppercase=False, color="#FFFFFF",
        highlight="", outline=0, box=True, position="bottom", max_words=12, max_chars=30, max_lines=2,
        effect="none",
    ),
    "minimal": CaptionStyle(
        template="minimal", font="Verdana", size=54, bold=True, uppercase=False, color="#FFFFFF",
        highlight="", outline=3, box=False, position="bottom", max_words=6, max_chars=26, max_lines=1,
        effect="none",
    ),
}  # fmt: skip

DEFAULT_TEMPLATE = "bold_pop"

# Fonts offered in the app, with the file to give libass. These ship with Windows.
FONTS: dict[str, str] = {
    "Arial Black": "ariblk.ttf",
    "Arial": "arialbd.ttf",
    "Impact": "impact.ttf",
    "Segoe UI Black": "seguibl.ttf",
    "Verdana": "verdanab.ttf",
    "Tahoma": "tahomabd.ttf",
}

# What the user may override on top of a template.
OVERRIDABLE = ("font", "size", "uppercase", "color", "highlight", "position")


def resolve(template: str | None, overrides: dict[str, Any] | None = None) -> CaptionStyle:
    base = TEMPLATES.get(template or DEFAULT_TEMPLATE, TEMPLATES[DEFAULT_TEMPLATE])
    changes = {k: v for k, v in (overrides or {}).items() if k in OVERRIDABLE and v is not None}
    if "font" in changes and changes["font"] not in FONTS:
        del changes["font"]
    if "size" in changes:
        changes["size"] = int(min(max(int(changes["size"]), 24), 200))
    if "position" in changes and changes["position"] not in ("top", "middle", "bottom"):
        del changes["position"]
    return replace(base, **changes)


def font_file(font: str) -> Path | None:
    """The installed file for one of FONTS, or None if it isn't on this system."""
    name = FONTS.get(font)
    if not name:
        return None
    if sys.platform == "win32":
        folders = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
    elif sys.platform == "darwin":
        folders = [Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"), Path.home() / "Library/Fonts"]
    else:
        folders = [Path("/usr/share/fonts"), Path.home() / ".fonts"]
    for folder in folders:
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return None
