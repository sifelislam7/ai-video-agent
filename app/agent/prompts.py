"""Prompt templates for the scriptwriting step."""

from __future__ import annotations

from ..schemas import CreateJobRequest

SYSTEM = """You are a senior short-form video strategist who writes viral TikTok \
content. You understand hooks, retention, pacing and platform-native tone.

Rules:
- Write in the requested language. If it is Arabic, use clear Modern Standard \
Arabic that still sounds natural and conversational (no stiff literary tone).
- The first scene MUST be a scroll-stopping hook (max ~12 words).
- Each scene narration is ONE or TWO short spoken sentences (max ~22 words) — \
it will be read aloud by a text-to-speech voice, so avoid emojis, markdown, \
abbreviations, URLs and parentheses inside the narration.
- `on_screen_text` is the burned-in caption: max 8 words, punchy, no emoji.
- `image_prompt` is for an image model. Always in ENGLISH, highly visual, \
describing subject + composition + lighting + mood. Never ask for text in the \
image. Vertical 9:16 framing.
- Keep facts safe and non-controversial; no medical, legal or financial advice \
presented as certainty.
- hashtags: 5 to 8, no "#" prefix, lowercase, relevant, mix broad and niche.

Return STRICT JSON only, matching this schema:
{
  "title": "string",
  "hook": "string",
  "caption": "string (TikTok caption, 1-2 lines, may include 1-2 emoji)",
  "hashtags": ["string"],
  "music_mood": "upbeat|calm|epic|mysterious",
  "scenes": [
    {"narration": "string", "on_screen_text": "string", "image_prompt": "string"}
  ]
}"""

_LANGUAGE_NAMES = {
    "ar": "Arabic (العربية)", "en": "English", "fr": "French",
    "es": "Spanish", "de": "German", "tr": "Turkish",
}


def build_brief(req: CreateJobRequest) -> str:
    """The user message. Keys are uppercase so the offline writer can parse it."""
    language = _LANGUAGE_NAMES.get(req.language[:2].lower(), req.language)
    lines = [
        f"TOPIC: {req.topic}",
        f"LANGUAGE: {req.language}",
        f"LANGUAGE_NAME: {language}",
        f"FORMAT: {'photo carousel' if req.kind.value == 'photo' else 'vertical video'}",
        f"SCENES: {req.scene_count}",
        f"TARGET_DURATION_SECONDS: {req.seconds}",
        f"STYLE: {req.style.value}",
        f"VOICEOVER: {'yes' if req.voiceover else 'no'}",
    ]
    if req.audience:
        lines.append(f"AUDIENCE: {req.audience}")
    if req.extra_instructions:
        lines.append(f"EXTRA_INSTRUCTIONS: {req.extra_instructions}")
    seconds_per_scene = max(req.seconds / max(req.scene_count, 1), 2.0)
    lines.append(
        f"PACING: about {seconds_per_scene:.1f} seconds per scene — size each "
        f"narration so it can be spoken in that time."
    )
    lines.append(f"Write exactly {req.scene_count} scenes. Answer with JSON only.")
    return "\n".join(lines)
