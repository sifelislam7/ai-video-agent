"""Provider contracts shared by every AI backend."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(180.0, connect=20.0)


class ProviderError(RuntimeError):
    """Raised when a provider cannot fulfil a request."""


@dataclass
class ProviderInfo:
    name: str
    kind: str
    available: bool
    detail: str = ""
    models: dict[str, str] = field(default_factory=dict)

    def dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "kind": self.kind, "available": self.available,
            "detail": self.detail, "models": self.models,
        }


class Provider(ABC):
    name: str = "base"
    kind: str = "base"

    @property
    @abstractmethod
    def available(self) -> bool:
        """True when the provider has everything it needs (keys, binaries...)."""

    def info(self) -> ProviderInfo:
        return ProviderInfo(self.name, self.kind, self.available)


class TextProvider(Provider):
    kind = "text"

    @abstractmethod
    async def complete_json(self, system: str, user: str, *, temperature: float = 0.8) -> dict:
        """Return a JSON object produced by the model."""


class ImageProvider(Provider):
    kind = "image"

    @abstractmethod
    async def generate(self, prompt: str, *, width: int, height: int, style: str = "") -> bytes:
        """Return raw image bytes (PNG/JPEG/WebP)."""


class TTSProvider(Provider):
    kind = "tts"

    @abstractmethod
    async def synthesize(self, text: str, *, language: str = "ar", voice: str = "") -> bytes:
        """Return raw audio bytes (mp3 or wav)."""


# ------------------------------------------------------------------ utilities
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(raw: str) -> dict:
    """Best-effort JSON extraction from an LLM answer."""
    if not raw:
        raise ProviderError("empty model response")
    raw = raw.strip()
    block = _JSON_BLOCK.search(raw)
    if block:
        raw = block.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ProviderError(f"model did not return valid JSON: {exc}") from exc
    raise ProviderError("model did not return JSON")
