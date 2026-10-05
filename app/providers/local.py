"""Offline providers — the fallback that makes the agent work with zero keys.

They are intentionally honest: the text provider is a structured template
writer (not an LLM), the image provider draws generative abstract art with
Pillow, and the TTS provider produces correctly timed silence so the video
still has the right pacing for captions.
"""

from __future__ import annotations

import asyncio
import io
import re
import tempfile
from pathlib import Path

from ..media import ffmpeg, imagekit
from .base import ImageProvider, TextProvider, TTSProvider

# --------------------------------------------------------------------- text
_AR = {
    "hooks": [
        "هل تعلم أن {topic} يغيّر قواعد اللعبة؟",
        "٣ أشياء عن {topic} لا أحد يخبرك بها",
        "توقف ثانية… هذا ما يجب أن تعرفه عن {topic}",
        "{topic} — ابدأ من هنا",
    ],
    "beats": [
        ("لنبدأ بالأساس: ما المقصود فعلًا بـ {topic} ولماذا يهمّك الآن؟", "ابدأ بالأساس"),
        ("المشكلة أن أغلب الناس يتعاملون مع {topic} بطريقة خاطئة تمامًا.", "الخطأ الشائع"),
        ("الخطوة الأولى بسيطة: ابدأ صغيرًا وركّز على نتيجة واحدة واضحة.", "ابدأ صغيرًا"),
        ("ما يصنع الفرق حقًا هو الاستمرارية اليومية وليس الكمال.", "الاستمرارية أهم من الكمال"),
        ("جرّب هذا اليوم وستلاحظ الفرق خلال أسبوع واحد فقط.", "جرّبها اليوم"),
        ("الخلاصة: {topic} ليس معقدًا، يحتاج خطة صغيرة وتنفيذًا يوميًا.", "الخلاصة"),
    ],
    "cta": "تابعنا لمزيد من المحتوى عن {topic} 👇",
    "tags": ["اكسبلور", "فائدة", "معلومات", "تيك_توك", "نصائح"],
}
_EN = {
    "hooks": [
        "Did you know {topic} changes everything?",
        "3 things about {topic} nobody tells you",
        "Stop scrolling — here is what {topic} really means",
        "{topic} — start here",
    ],
    "beats": [
        ("Let's start with the basics: what {topic} really is and why it matters now.", "Start with the basics"),
        ("The problem is that most people approach {topic} the wrong way.", "The common mistake"),
        ("Step one is simple: start small and aim at one clear outcome.", "Start small"),
        ("What makes the difference is daily consistency, not perfection.", "Consistency beats perfection"),
        ("Try this today and you will notice the change within a week.", "Try it today"),
        ("Bottom line: {topic} isn't complex, it needs a plan and daily reps.", "Bottom line"),
    ],
    "cta": "Follow for more on {topic} 👇",
    "tags": ["fyp", "learn", "tips", "viral", "howto"],
}

_VISUAL_HINTS = [
    "wide establishing shot, volumetric light, shallow depth of field",
    "close-up detail, soft rim lighting, bokeh background",
    "dynamic low angle, dramatic contrast, motion blur",
    "flat-lay top view, clean composition, soft shadows",
    "silhouette against a bright gradient sky, golden hour",
    "macro texture, high detail, cinematic colour grade",
]


def _slugify_tag(value: str) -> str:
    value = re.sub(r"[^\w\u0600-\u06FF ]+", "", value).strip()
    return re.sub(r"\s+", "_", value)[:24]


class LocalTextProvider(TextProvider):
    name = "local"

    @property
    def available(self) -> bool:
        return True

    async def complete_json(self, system: str, user: str, *, temperature: float = 0.8) -> dict:
        """Builds a plan from the embedded brief without calling any model."""
        topic = _field(user, "TOPIC") or "موضوع اليوم"
        language = (_field(user, "LANGUAGE") or "ar").lower()
        try:
            count = int(_field(user, "SCENES") or 5)
        except ValueError:
            count = 5
        style = _field(user, "STYLE") or "cinematic"
        pack = _AR if language.startswith("ar") else _EN

        hook = pack["hooks"][len(topic) % len(pack["hooks"])].format(topic=topic)
        beats = pack["beats"]
        short_topic = _shorten(topic, 34)
        scenes = []
        for i in range(count):
            narration, overlay = beats[i % len(beats)]
            scenes.append({
                "narration": narration.format(topic=topic),
                "on_screen_text": overlay if i else short_topic,
                "image_prompt": (
                    f"{style} visual about {topic}, scene {i + 1}, "
                    f"{_VISUAL_HINTS[i % len(_VISUAL_HINTS)]}, vertical 9:16"
                ),
            })
        tags = [_slugify_tag(topic)] + pack["tags"]
        return {
            "title": _shorten(topic, 60),
            "hook": hook,
            "caption": f"{hook}\n{pack['cta'].format(topic=topic)}",
            "hashtags": [t for t in tags if t][:8],
            "music_mood": "upbeat",
            "scenes": scenes,
        }


def _field(text: str, key: str) -> str:
    match = re.search(rf"^{key}:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _shorten(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    cut = value[:limit].rsplit(" ", 1)[0]
    return (cut or value[:limit]).rstrip(" ،,.") + "…"


# -------------------------------------------------------------------- image
class LocalImageProvider(ImageProvider):
    name = "local"

    @property
    def available(self) -> bool:
        return True

    async def generate(self, prompt: str, *, width: int, height: int, style: str = "") -> bytes:
        def _draw() -> bytes:
            image = imagekit.generate_background(prompt, (width, height), style or "cinematic")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()

        return await asyncio.to_thread(_draw)


# ---------------------------------------------------------------------- tts
# Average speaking rates used to time captions when no real voice is available.
_CHARS_PER_SECOND = {"ar": 11.0, "en": 14.0, "fr": 13.0, "es": 14.0}


def estimate_duration(text: str, language: str = "ar") -> float:
    rate = _CHARS_PER_SECOND.get(language[:2].lower(), 13.0)
    words = max(len(text.split()), 1)
    by_chars = len(text) / rate
    by_words = words / 2.6  # ~2.6 words per second
    return max(2.0, min(14.0, max(by_chars, by_words) + 0.45))


class LocalTTSProvider(TTSProvider):
    """Generates silence with the right duration (keeps pacing correct)."""

    name = "local"

    @property
    def available(self) -> bool:
        return True

    async def synthesize(self, text: str, *, language: str = "ar", voice: str = "") -> bytes:
        duration = estimate_duration(text, language)

        def _render() -> bytes:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "silence.wav"
                ffmpeg.make_silence(duration, path)
                return path.read_bytes()

        return await asyncio.to_thread(_render)


__all__ = [
    "LocalTextProvider", "LocalImageProvider", "LocalTTSProvider",
    "estimate_duration",
]
