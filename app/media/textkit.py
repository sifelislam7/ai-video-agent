"""Text rendering helpers — including proper Arabic shaping + RTL ordering.

Pillow has no built-in Arabic shaper (libraqm is usually absent from wheels), so
text is reshaped into Unicode presentation forms with ``arabic-reshaper`` and
reordered with ``python-bidi`` before it is drawn.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import ImageDraw, ImageFont

from ..config import FONTS_DIR

log = logging.getLogger(__name__)

_ARABIC_RANGES = (
    (0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF), (0xFE70, 0xFEFF),
)

# Fonts bundled with the repo, best first.
_BUNDLED_ARABIC = ["NotoSansArabic_700Bold.ttf", "Cairo_700Bold.ttf", "Cairo_900Black.ttf"]
_BUNDLED_LATIN = ["Cairo_700Bold.ttf", "Cairo_900Black.ttf", "NotoSansArabic_700Bold.ttf"]

# Where to look when nothing is bundled (Linux / macOS / Windows).
_SYSTEM_FONT_DIRS = [
    "/usr/share/fonts", "/usr/local/share/fonts", str(Path.home() / ".fonts"),
    "/Library/Fonts", "/System/Library/Fonts", str(Path.home() / "Library/Fonts"),
    "C:/Windows/Fonts",
]
_SYSTEM_ARABIC_HINTS = (
    "notosansarabic", "notonaskh", "amiri", "cairo", "tajawal", "dubai",
    "geezapro", "arial", "tahoma", "segoeui",
)


def is_rtl(text: str) -> bool:
    """True when the string contains a meaningful amount of Arabic script."""
    for ch in text:
        code = ord(ch)
        if any(lo <= code <= hi for lo, hi in _ARABIC_RANGES):
            return True
    return False


@lru_cache(maxsize=64)
def _covers_arabic(font_path: str) -> bool:
    try:
        from fontTools.ttLib import TTFont

        font = TTFont(font_path, fontNumber=0, lazy=True)
        codes: set[int] = set()
        for table in font["cmap"].tables:
            codes |= set(table.cmap.keys())
        font.close()
        # Needs base letters *and* presentation forms (we feed shaped text).
        base = sum(1 for c in codes if 0x0620 <= c <= 0x064A)
        forms = sum(1 for c in codes if 0xFE70 <= c <= 0xFEFC)
        return base > 20 and forms > 40
    except Exception:
        return False


@lru_cache(maxsize=4)
def find_font(arabic: bool = True) -> str:
    """Locate a usable font file, preferring the bundled ones."""
    names = _BUNDLED_ARABIC if arabic else _BUNDLED_LATIN
    for name in names:
        candidate = FONTS_DIR / name
        if candidate.exists():
            if not arabic or _covers_arabic(str(candidate)):
                return str(candidate)
    # Any bundled ttf.
    for candidate in sorted(FONTS_DIR.glob("*.ttf")):
        if not arabic or _covers_arabic(str(candidate)):
            return str(candidate)
    # System scan.
    for directory in _SYSTEM_FONT_DIRS:
        base = Path(directory)
        if not base.exists():
            continue
        for candidate in base.rglob("*.tt[fc]"):
            stem = candidate.stem.lower().replace(" ", "").replace("-", "")
            if arabic:
                if any(hint in stem for hint in _SYSTEM_ARABIC_HINTS) and _covers_arabic(
                    str(candidate)
                ):
                    return str(candidate)
            elif "dejavusans" in stem or "arial" in stem:
                return str(candidate)
    fallback = next(iter(sorted(FONTS_DIR.glob("*.ttf"))), None)
    if fallback:
        log.warning("No Arabic-capable font found; falling back to %s", fallback)
        return str(fallback)
    raise FileNotFoundError(
        "No font available. Run `python scripts/fetch_fonts.py` or drop a .ttf into assets/fonts/."
    )


@lru_cache(maxsize=128)
def load_font(size: int, arabic: bool = True) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(find_font(arabic), size)


def shape(text: str) -> str:
    """Reshape + bidi-reorder Arabic so Pillow draws it correctly."""
    if not text or not is_rtl(text):
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        reshaper = arabic_reshaper.ArabicReshaper(
            arabic_reshaper.config_for_true_type_font(
                find_font(True), arabic_reshaper.ENABLE_ALL_LIGATURES
            )
        )
        return get_display(reshaper.reshape(text))
    except Exception:  # pragma: no cover - degraded but still renders
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display

            return get_display(arabic_reshaper.reshape(text))
        except Exception:
            return text


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "")
    return re.sub(r"[ \t]+", " ", text).strip()


def wrap(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    draw: ImageDraw.ImageDraw | None = None,
) -> list[str]:
    """Greedy word wrap measured with the real font metrics (pre-shaping)."""
    words = normalize(text).split(" ")
    lines: list[str] = []
    current = ""

    def width_of(value: str) -> float:
        probe = shape(value)
        if draw is not None:
            return draw.textlength(probe, font=font)
        return font.getlength(probe)

    for word in words:
        candidate = f"{current} {word}".strip()
        if current and width_of(candidate) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


@dataclass
class TextBlock:
    lines: list[str]
    font: ImageFont.FreeTypeFont
    line_height: int
    width: int
    height: int


def layout(
    text: str,
    max_width: int,
    max_height: int,
    *,
    start_size: int = 72,
    min_size: int = 28,
    line_spacing: float = 1.25,
    arabic: bool | None = None,
) -> TextBlock:
    """Shrink-to-fit text layout inside a box."""
    arabic = is_rtl(text) if arabic is None else arabic
    size = start_size
    while size >= min_size:
        font = load_font(size, arabic)
        lines = wrap(text, font, max_width)
        line_height = int(size * line_spacing)
        if line_height * len(lines) <= max_height:
            widest = max((font.getlength(shape(l)) for l in lines), default=0)
            return TextBlock(lines, font, line_height, int(widest), line_height * len(lines))
        size -= 4
    font = load_font(min_size, arabic)
    lines = wrap(text, font, max_width)
    line_height = int(min_size * line_spacing)
    return TextBlock(lines, font, line_height, max_width, line_height * len(lines))


def draw_block(
    draw: ImageDraw.ImageDraw,
    block: TextBlock,
    center_x: int,
    top_y: int,
    *,
    fill: tuple[int, int, int] = (255, 255, 255),
    stroke_fill: tuple[int, int, int] = (0, 0, 0),
    stroke_width: int = 0,
    shadow: bool = True,
) -> None:
    y = top_y
    for line in block.lines:
        rendered = shape(line)
        if shadow:
            draw.text(
                (center_x + 3, y + 4), rendered, font=block.font,
                fill=(0, 0, 0), anchor="ma",
            )
        draw.text(
            (center_x, y), rendered, font=block.font, fill=fill,
            anchor="ma", stroke_width=stroke_width, stroke_fill=stroke_fill,
        )
        y += block.line_height
