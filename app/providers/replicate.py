"""Replicate image (and optional video) models, e.g. FLUX."""

from __future__ import annotations

import asyncio

import httpx

from ..config import Settings
from .base import DEFAULT_TIMEOUT, ImageProvider, ProviderError, ProviderInfo

API_BASE = "https://api.replicate.com/v1"


def _aspect(width: int, height: int) -> str:
    ratio = width / height
    table = {"9:16": 9 / 16, "1:1": 1.0, "4:5": 0.8, "16:9": 16 / 9, "3:4": 0.75}
    return min(table, key=lambda key: abs(table[key] - ratio))


class ReplicateImage(ImageProvider):
    name = "replicate"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.token = settings.replicate_api_token
        self.model = settings.replicate_image_model

    @property
    def available(self) -> bool:
        return bool(self.token and self.model)

    def info(self) -> ProviderInfo:
        return ProviderInfo(self.name, self.kind, self.available,
                            "REPLICATE_API_TOKEN" if not self.available else "",
                            {"image": self.model})

    async def generate(self, prompt: str, *, width: int, height: int, style: str = "") -> bytes:
        if not self.available:
            raise ProviderError("REPLICATE_API_TOKEN / REPLICATE_IMAGE_MODEL not set")
        body = {
            "input": {
                "prompt": f"{prompt}. Style: {style}." if style else prompt,
                "aspect_ratio": _aspect(width, height),
                "output_format": "png",
                "num_outputs": 1,
            }
        }
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Prefer": "wait",
        }
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(
                f"{API_BASE}/models/{self.model}/predictions", headers=headers, json=body
            )
            if response.status_code >= 400:
                raise ProviderError(
                    f"Replicate failed ({response.status_code}): {response.text[:400]}"
                )
            prediction = response.json()
            # `Prefer: wait` usually returns the finished prediction; poll otherwise.
            for _ in range(60):
                status = prediction.get("status")
                if status == "succeeded":
                    break
                if status in {"failed", "canceled"}:
                    raise ProviderError(f"Replicate prediction {status}: {prediction.get('error')}")
                await asyncio.sleep(2)
                poll = await client.get(
                    prediction["urls"]["get"], headers={"Authorization": f"Bearer {self.token}"}
                )
                prediction = poll.json()
            output = prediction.get("output")
            url = output[0] if isinstance(output, list) else output
            if not url:
                raise ProviderError("Replicate returned no output")
            image = await client.get(url)
            return image.content
