from __future__ import annotations

from app.media import textkit


def test_detects_arabic():
    assert textkit.is_rtl("مرحبا بالعالم")
    assert not textkit.is_rtl("hello world")


def test_font_supports_arabic_presentation_forms():
    path = textkit.find_font(arabic=True)
    assert path.endswith((".ttf", ".ttc", ".otf"))
    assert textkit._covers_arabic(path), "bundled font must cover Arabic glyphs"


def test_shaping_produces_presentation_forms():
    shaped = textkit.shape("مرحبا")
    assert shaped != "مرحبا"
    # Reshaped text uses the Arabic Presentation Forms-B block.
    assert any(0xFE70 <= ord(ch) <= 0xFEFF for ch in shaped)


def test_shaping_leaves_latin_untouched():
    assert textkit.shape("Hello 123") == "Hello 123"


def test_wrap_respects_width():
    font = textkit.load_font(48, True)
    lines = textkit.wrap("كلمة " * 30, font, 600)
    assert len(lines) > 1
    assert all(font.getlength(textkit.shape(line)) <= 640 for line in lines)


def test_layout_shrinks_to_fit():
    block = textkit.layout("نص طويل جدا " * 12, 500, 300, start_size=90, min_size=20)
    assert block.height <= 300 or block.font.size == 20
    assert block.lines
