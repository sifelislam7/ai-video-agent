"""OpenAI-compatible providers (also powers OpenRouter / any compatible gateway)."""

from __future__ import annotations

import base64

import httpx

from ..config import Settings
from .base import (
    DEFAULT_TIMEOUT,
    ImageProvider,
    ProviderError,
    ProviderInfo,
    TTSProvider,
    TextProvider,
    extract_json,
)


def _vertical_size(width: int, height: int) -> str:
    if height > width:
        return "1024x1536"
    if width > height:
        return "1536x1024"
    return "1024x1024"


class OpenAIText(TextProvider):
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.base_url = settings.openai_base_url.rstrip("/")
        self.api_key = settings.openai_api_key
        self.model = settings.openai_text_model

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def info(self) -> ProviderInfo:
        return ProviderInfo(self.name, self.kind, self.available,
                            "OPENAI_API_KEY" if not self.available else "",
                            {"text": self.model})

    async def complete_json(self, system: str, user: str, *, temperature: float = 0.8) -> dict:
        if not self.available:
            raise ProviderError("OPENAI_API_KEY is not set")
        payload = {
            "model": self.model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        if response.status_code >= 400:
            raise ProviderError(f"OpenAI chat failed ({response.status_code}): {response.text[:400]}")
        data = response.json()
        return extract_json(data["choices"][0]["message"]["content"])


class OpenRouterText(OpenAIText):
    name = "openrouter"

    def __init__(self, settings: Settings) -> None:  # noqa: D107
        self.s = settings
        self.base_url = settings.openrouter_base_url.rstrip("/")
        self.api_key = settings.openrouter_api_key
        self.model = settings.openrouter_text_model

    def info(self) -> ProviderInfo:
        return ProviderInfo(self.name, self.kind, self.available,
                            "OPENROUTER_API_KEY" if not self.available else "",
                            {"text": self.model})


class OpenAIImage(ImageProvider):
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.base_url = settings.openai_base_url.rstrip("/")
        self.api_key = settings.openai_api_key
        self.model = settings.openai_image_model

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def info(self) -> ProviderInfo:
        return ProviderInfo(self.name, self.kind, self.available,
                            "OPENAI_API_KEY" if not self.available else "",
                            {"image": self.model})

    async def generate(self, prompt: str, *, width: int, height: int, style: str = "") -> bytes:
        if not self.available:
            raise ProviderError("OPENAI_API_KEY is not set")
        payload = {
            "model": self.model,
            "prompt": prompt if not style else f"{prompt}. Style: {style}.",
            "size": _vertical_size(width, height),
            "n": 1,
        }
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(
                f"{self.base_url}/images/generations",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        if response.status_code >= 400:
            raise ProviderError(f"OpenAI image failed ({response.status_code}): {response.text[:400]}")
        item = response.json()["data"][0]
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            raw = await client.get(item["url"])
        return raw.content


class OpenAITTS(TTSProvider):
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.base_url = settings.openai_base_url.rstrip("/")
        self.api_key = settings.openai_api_key
        self.model = settings.openai_tts_model
        self.voice = settings.openai_tts_voice

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def info(self) -> ProviderInfo:
        return ProviderInfo(self.name, self.kind, self.available,
                            "OPENAI_API_KEY" if not self.available else "",
                            {"tts": self.model, "voice": self.voice})

    async def synthesize(self, text: str, *, language: str = "ar", voice: str = "") -> bytes:
        if not self.available:
            raise ProviderError("OPENAI_API_KEY is not set")
        payload = {
            "model": self.model,
            "voice": voice or self.voice,
            "input": text,
            "response_format": "mp3",
        }
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(
                f"{self.base_url}/audio/speech",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        if response.status_code >= 400:
            raise ProviderError(f"OpenAI TTS failed ({response.status_code}): {response.text[:400]}")
        return response.content
