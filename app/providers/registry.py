"""Provider registry — picks a backend per capability with graceful fallback."""

from __future__ import annotations

import logging
from typing import Any

from ..config import Settings, get_settings
from .base import ImageProvider, Provider, TTSProvider, TextProvider
from .elevenlabs import ElevenLabsTTS
from .gemini import GeminiImage, GeminiText
from .local import LocalImageProvider, LocalTextProvider, LocalTTSProvider
from .openai import OpenAIImage, OpenAIText, OpenAITTS, OpenRouterText
from .replicate import ReplicateImage

log = logging.getLogger(__name__)

# Preference order used when the provider is set to "auto".
_TEXT_ORDER = ["openai", "gemini", "openrouter", "local"]
_IMAGE_ORDER = ["openai", "gemini", "replicate", "local"]
_TTS_ORDER = ["elevenlabs", "openai", "local"]


def _text_map(s: Settings) -> dict[str, TextProvider]:
    return {
        "openai": OpenAIText(s),
        "gemini": GeminiText(s),
        "openrouter": OpenRouterText(s),
        "local": LocalTextProvider(),
    }


def _image_map(s: Settings) -> dict[str, ImageProvider]:
    return {
        "openai": OpenAIImage(s),
        "gemini": GeminiImage(s),
        "replicate": ReplicateImage(s),
        "local": LocalImageProvider(),
    }


def _tts_map(s: Settings) -> dict[str, TTSProvider]:
    return {
        "elevenlabs": ElevenLabsTTS(s),
        "openai": OpenAITTS(s),
        "local": LocalTTSProvider(),
    }


def _pick(mapping: dict[str, Any], order: list[str], requested: str) -> Provider:
    requested = (requested or "auto").strip().lower()
    if requested not in {"", "auto"}:
        provider = mapping.get(requested)
        if provider is None:
            log.warning("Unknown provider '%s'; falling back to auto", requested)
        elif provider.available:
            return provider
        else:
            log.warning("Provider '%s' is not configured; falling back", requested)
    for name in order:
        provider = mapping.get(name)
        if provider is not None and provider.available:
            return provider
    return mapping["local"]


def resolve_text(settings: Settings | None = None, requested: str | None = None) -> TextProvider:
    s = settings or get_settings()
    return _pick(_text_map(s), _TEXT_ORDER, requested or s.text_provider)  # type: ignore[return-value]


def resolve_image(settings: Settings | None = None, requested: str | None = None) -> ImageProvider:
    s = settings or get_settings()
    return _pick(_image_map(s), _IMAGE_ORDER, requested or s.image_provider)  # type: ignore[return-value]


def resolve_tts(settings: Settings | None = None, requested: str | None = None) -> TTSProvider:
    s = settings or get_settings()
    return _pick(_tts_map(s), _TTS_ORDER, requested or s.tts_provider)  # type: ignore[return-value]


def describe(settings: Settings | None = None) -> dict[str, Any]:
    """Snapshot of every provider — powers the status panel in the web UI."""
    s = settings or get_settings()
    return {
        "text": {
            "selected": resolve_text(s).name,
            "configured": s.text_provider,
            "providers": [p.info().dict() for p in _text_map(s).values()],
        },
        "image": {
            "selected": resolve_image(s).name,
            "configured": s.image_provider,
            "providers": [p.info().dict() for p in _image_map(s).values()],
        },
        "tts": {
            "selected": resolve_tts(s).name,
            "configured": s.tts_provider,
            "providers": [p.info().dict() for p in _tts_map(s).values()],
        },
        "tiktok": {
            "mode": "live" if s.live_tiktok else "mock",
            "configured": s.tiktok_configured,
            "upload_source": s.tiktok_upload_source,
            "post_target": s.tiktok_post_target,
            "privacy_level": s.tiktok_privacy_level,
        },
    }
