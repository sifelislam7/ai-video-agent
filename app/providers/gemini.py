"""Google Gemini providers (text + image)."""

from __future__ import annotations

import base64

import httpx

from ..config import Settings
from .base import (
    DEFAULT_TIMEOUT,
    ImageProvider,
    ProviderError,
    ProviderInfo,
    TextProvider,
    extract_json,
)


class GeminiText(TextProvider):
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.base_url = settings.gemini_base_url.rstrip("/")
        self.api_key = settings.gemini_api_key
        self.model = settings.gemini_text_model

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def info(self) -> ProviderInfo:
        return ProviderInfo(self.name, self.kind, self.available,
                            "GEMINI_API_KEY" if not self.available else "",
                            {"text": self.model})

    async def complete_json(self, system: str, user: str, *, temperature: float = 0.8) -> dict:
        if not self.available:
            raise ProviderError("GEMINI_API_KEY is not set")
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
            },
        }
        url = f"{self.base_url}/models/{self.model}:generateContent"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(
                url, headers={"x-goog-api-key": self.api_key}, json=payload
            )
        if response.status_code >= 400:
            raise ProviderError(f"Gemini failed ({response.status_code}): {response.text[:400]}")
        data = response.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"unexpected Gemini response: {str(data)[:300]}") from exc
        return extract_json(text)


class GeminiImage(ImageProvider):
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.base_url = settings.gemini_base_url.rstrip("/")
        self.api_key = settings.gemini_api_key
        self.model = settings.gemini_image_model

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def info(self) -> ProviderInfo:
        return ProviderInfo(self.name, self.kind, self.available,
                            "GEMINI_API_KEY" if not self.available else "",
                            {"image": self.model})

    async def generate(self, prompt: str, *, width: int, height: int, style: str = "") -> bytes:
        if not self.available:
            raise ProviderError("GEMINI_API_KEY is not set")
        full_prompt = (
            f"{prompt}. {('Style: ' + style + '. ') if style else ''}"
            f"Vertical {width}x{height} (9:16) composition, no text, no watermark."
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": full_prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
        url = f"{self.base_url}/models/{self.model}:generateContent"
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(
                url, headers={"x-goog-api-key": self.api_key}, json=payload
            )
        if response.status_code >= 400:
            raise ProviderError(f"Gemini image failed ({response.status_code}): {response.text[:400]}")
        data = response.json()
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"])
        raise ProviderError("Gemini returned no image data")
