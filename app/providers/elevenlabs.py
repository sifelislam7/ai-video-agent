"""ElevenLabs text-to-speech (great multilingual Arabic voices)."""

from __future__ import annotations

import httpx

from ..config import Settings
from .base import DEFAULT_TIMEOUT, ProviderError, ProviderInfo, TTSProvider

API_BASE = "https://api.elevenlabs.io/v1"


class ElevenLabsTTS(TTSProvider):
    name = "elevenlabs"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.api_key = settings.elevenlabs_api_key
        self.voice_id = settings.elevenlabs_voice_id
        self.model = settings.elevenlabs_model

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def info(self) -> ProviderInfo:
        return ProviderInfo(self.name, self.kind, self.available,
                            "ELEVENLABS_API_KEY" if not self.available else "",
                            {"tts": self.model, "voice": self.voice_id})

    async def synthesize(self, text: str, *, language: str = "ar", voice: str = "") -> bytes:
        if not self.available:
            raise ProviderError("ELEVENLABS_API_KEY is not set")
        voice_id = voice or self.voice_id
        payload = {
            "text": text,
            "model_id": self.model,
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.25},
        }
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(
                f"{API_BASE}/text-to-speech/{voice_id}",
                headers={"xi-api-key": self.api_key, "accept": "audio/mpeg"},
                json=payload,
                params={"output_format": "mp3_44100_128"},
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"ElevenLabs failed ({response.status_code}): {response.text[:400]}"
            )
        return response.content
