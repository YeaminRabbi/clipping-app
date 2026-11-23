"""Advanced SubStation Alpha subtitles for burning captions in with libass."""

from .cues import Cue, wrap
from .styles import REFERENCE_HEIGHT, CaptionStyle


def _ass_color(hex_rgb: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR (alpha 0 = opaque)."""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _time(ms: int) -> str:
    ms = max(0, ms)
    cs = round(ms / 10)
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _clean(text: str) -> str:
    """Remove characters that ASS treats as markup."""
    return text.replace("\\", "").replace("{", "").replace("}", "")


def build_ass(cues: list[Cue], style: CaptionStyle, width: int, height: int, offset_ms: int) -> str:
    scale = height / REFERENCE_HEIGHT
    size = round(style.size * scale)
    outline = round(style.outline * scale)
    margin_lr = round(width * 0.08)
    alignment, margin_v = {
        "bottom": (2, round(height * 0.12)),
        "middle": (5, 0),
        "top": (8, round(height * 0.10)),
    }[style.position]
    primary, secondary = _ass_color(style.color), _ass_color(style.color)
    if style.effect == "karaoke" and style.highlight:
        # Karaoke fills each word from the secondary colour to the primary as it's spoken.
        primary = _ass_color(style.highlight)
    if style.box:
        border_style, outline_color, back_color, outline, shadow = 3, _ass_color("#000000", 0x60), _ass_color("#000000", 0x60), round(14 * scale), 0
    else:
        border_style, outline_color, back_color, shadow = 1, _ass_color("#000000"), _ass_color("#000000", 0x80), round(2 * scale)

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Caption,{style.font},{size},{primary},{secondary},{outline_color},{back_color},"
        f"{-1 if style.bold else 0},0,0,0,100,100,0,0,{border_style},{outline},{shadow},{alignment},"
        f"{margin_lr},{margin_lr},{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    def event(start: int, end: int, text: str) -> str:
        return f"Dialogue: 0,{_time(start - offset_ms)},{_time(end - offset_ms)},Caption,,0,0,0,,{text}"

    for cue in cues:
        words = [_clean(w["text"].upper() if style.uppercase else w["text"]) for w in cue.words]
        if style.effect == "pop" and style.highlight:
            # One event per word: the whole cue, with the spoken word coloured and slightly larger.
            hl = _ass_color(style.highlight)
            for i, w in enumerate(cue.words):
                start = cue.start if i == 0 else w["start"]
                end = cue.words[i + 1]["start"] if i + 1 < len(cue.words) else cue.end
                if end <= start:
                    continue
                parts = [
                    f"{{\\c{hl}\\fscx110\\fscy110}}{word}{{\\r}}" if j == i else word for j, word in enumerate(words)
                ]
                lines.append(event(start, end, _wrap_tagged(parts, words, style)))
        elif style.effect == "karaoke":
            parts = []
            for i, w in enumerate(cue.words):
                until = cue.words[i + 1]["start"] if i + 1 < len(cue.words) else w["end"]
                parts.append(f"{{\\kf{max(1, round((until - (cue.start if i == 0 else w['start'])) / 10))}}}{words[i]}")
            lines.append(event(cue.start, cue.end, _wrap_tagged(parts, words, style)))
        else:
            lines.append(event(cue.start, cue.end, wrap(" ".join(words), style.max_chars, style.max_lines).replace("\n", "\\N")))
    return "\n".join(lines) + "\n"


def _wrap_tagged(parts: list[str], plain: list[str], style: CaptionStyle) -> str:
    """Join tagged words, inserting the same line break that plain wrapping would choose."""
    wrapped = wrap(" ".join(plain), style.max_chars, style.max_lines)
    if "\n" not in wrapped:
        return " ".join(parts)
    first_line_words = len(wrapped.split("\n")[0].split())
    return " ".join(parts[:first_line_words]) + "\\N" + " ".join(parts[first_line_words:])
