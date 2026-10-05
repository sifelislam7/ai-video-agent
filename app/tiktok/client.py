"""TikTok Content Posting API client.

Two interchangeable implementations behind one interface:

* :class:`LiveTikTokClient` — the real API (``open.tiktokapis.com``).
* :class:`MockTikTokClient` — records the publish locally, so the whole agent
  can be exercised end-to-end without developer credentials.

Reference: https://developers.tiktok.com/doc/content-posting-api-get-started
"""

from __future__ import annotations

import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..config import DATA_DIR, Settings
from ..schemas import Account
from ..storage import utcnow

log = logging.getLogger(__name__)

API = "https://open.tiktokapis.com/v2"
CREATOR_INFO_URL = f"{API}/post/publish/creator_info/query/"
VIDEO_INIT_URL = f"{API}/post/publish/video/init/"
INBOX_VIDEO_INIT_URL = f"{API}/post/publish/inbox/video/init/"
CONTENT_INIT_URL = f"{API}/post/publish/content/init/"
STATUS_URL = f"{API}/post/publish/status/fetch/"

# TikTok chunk rules: 5MB-64MB per chunk, the final chunk may reach 128MB,
# at most 1000 chunks, and a file below 5MB must be sent as a single chunk.
MIN_CHUNK = 5 * 1024 * 1024
DEFAULT_CHUNK = 10 * 1024 * 1024

MAX_TITLE = 2200


class TikTokError(RuntimeError):
    pass


@dataclass
class PublishResult:
    publish_id: str
    status: str
    mode: str
    target: str
    media: str
    detail: dict[str, Any]

    def dict(self) -> dict[str, Any]:
        return {
            "publish_id": self.publish_id, "status": self.status, "mode": self.mode,
            "target": self.target, "media": self.media, "detail": self.detail,
            "at": utcnow().isoformat(),
        }


def chunk_plan(size: int) -> tuple[int, int]:
    """Return ``(chunk_size, total_chunk_count)`` honouring TikTok's rules."""
    if size <= MIN_CHUNK:
        return size, 1
    chunk_size = DEFAULT_CHUNK
    total = size // chunk_size
    if total > 1000:
        total = 1000
        chunk_size = size // total
    return chunk_size, max(total, 1)


class BaseTikTokClient(ABC):
    mode = "base"

    @abstractmethod
    async def creator_info(self, account: Account) -> dict: ...

    @abstractmethod
    async def publish_video(
        self, account: Account, video_path: Path, caption: str, *,
        privacy_level: str = "SELF_ONLY", target: str = "DIRECT_POST",
        video_url: str | None = None, cover_ms: int = 1000,
    ) -> PublishResult: ...

    @abstractmethod
    async def publish_photos(
        self, account: Account, photo_urls: list[str], title: str, caption: str, *,
        privacy_level: str = "SELF_ONLY", target: str = "DIRECT_POST", cover_index: int = 0,
    ) -> PublishResult: ...

    @abstractmethod
    async def fetch_status(self, account: Account, publish_id: str) -> dict: ...


# --------------------------------------------------------------------- mock
class MockTikTokClient(BaseTikTokClient):
    """Writes a JSON record under ``data/mock_posts`` instead of calling TikTok."""

    mode = "mock"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.dir = DATA_DIR / "mock_posts"
        self.dir.mkdir(parents=True, exist_ok=True)

    async def creator_info(self, account: Account) -> dict:
        return {
            "creator_nickname": account.display_name or "Mock Creator",
            "creator_username": "mock_creator",
            "privacy_level_options": [
                "PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS",
                "FOLLOWER_OF_CREATOR", "SELF_ONLY",
            ],
            "comment_disabled": False,
            "duet_disabled": False,
            "stitch_disabled": False,
            "max_video_post_duration_sec": 600,
            "_mock": True,
        }

    def _record(self, payload: dict) -> PublishResult:
        publish_id = f"mock_{uuid.uuid4().hex[:16]}"
        payload = {"publish_id": publish_id, **payload, "created_at": utcnow().isoformat()}
        (self.dir / f"{publish_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("[mock] recorded TikTok post %s", publish_id)
        return PublishResult(
            publish_id=publish_id, status="PUBLISH_COMPLETE", mode="mock",
            target=payload.get("target", "DIRECT_POST"),
            media=payload.get("media", "VIDEO"), detail=payload,
        )

    async def publish_video(
        self, account: Account, video_path: Path, caption: str, *,
        privacy_level: str = "SELF_ONLY", target: str = "DIRECT_POST",
        video_url: str | None = None, cover_ms: int = 1000,
    ) -> PublishResult:
        size = Path(video_path).stat().st_size if Path(video_path).exists() else 0
        return self._record({
            "media": "VIDEO", "target": target, "account_id": account.id,
            "caption": caption[:MAX_TITLE], "privacy_level": privacy_level,
            "video_path": str(video_path), "video_url": video_url,
            "video_size": size, "chunking": chunk_plan(size) if size else None,
        })

    async def publish_photos(
        self, account: Account, photo_urls: list[str], title: str, caption: str, *,
        privacy_level: str = "SELF_ONLY", target: str = "DIRECT_POST", cover_index: int = 0,
    ) -> PublishResult:
        return self._record({
            "media": "PHOTO", "target": target, "account_id": account.id,
            "title": title[:90], "caption": caption[:MAX_TITLE],
            "privacy_level": privacy_level, "photo_images": photo_urls,
            "photo_cover_index": cover_index,
        })

    async def fetch_status(self, account: Account, publish_id: str) -> dict:
        path = self.dir / f"{publish_id}.json"
        if not path.exists():
            raise TikTokError(f"unknown mock publish_id {publish_id}")
        return {"status": "PUBLISH_COMPLETE", **json.loads(path.read_text(encoding="utf-8"))}


# --------------------------------------------------------------------- live
class LiveTikTokClient(BaseTikTokClient):
    mode = "live"

    def __init__(self, settings: Settings) -> None:
        self.s = settings

    @staticmethod
    def _headers(account: Account) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {account.access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    @staticmethod
    def _unwrap(payload: dict, context: str) -> dict:
        error = payload.get("error") or {}
        code = error.get("code", "ok")
        if code and code != "ok":
            raise TikTokError(
                f"{context} failed: {code} — {error.get('message')} "
                f"(log_id={error.get('log_id')})"
            )
        return payload.get("data", {})

    async def creator_info(self, account: Account) -> dict:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(CREATOR_INFO_URL, headers=self._headers(account))
        return self._unwrap(response.json(), "creator_info")

    async def publish_video(
        self, account: Account, video_path: Path, caption: str, *,
        privacy_level: str = "SELF_ONLY", target: str = "DIRECT_POST",
        video_url: str | None = None, cover_ms: int = 1000,
    ) -> PublishResult:
        video_path = Path(video_path)
        direct = target.upper() == "DIRECT_POST"
        url = VIDEO_INIT_URL if direct else INBOX_VIDEO_INIT_URL

        if video_url:
            source_info: dict[str, Any] = {"source": "PULL_FROM_URL", "video_url": video_url}
            size = 0
        else:
            if not video_path.exists():
                raise TikTokError(f"video not found: {video_path}")
            size = video_path.stat().st_size
            chunk_size, total = chunk_plan(size)
            source_info = {
                "source": "FILE_UPLOAD", "video_size": size,
                "chunk_size": chunk_size, "total_chunk_count": total,
            }

        body: dict[str, Any] = {"source_info": source_info}
        if direct:
            body["post_info"] = {
                "title": caption[:MAX_TITLE],
                "privacy_level": privacy_level,
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
                "video_cover_timestamp_ms": cover_ms,
            }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, headers=self._headers(account), json=body)
            data = self._unwrap(response.json(), "video/init")
            publish_id = data.get("publish_id", "")
            upload_url = data.get("upload_url")
            if upload_url and not video_url:
                await self._upload_file(client, upload_url, video_path, source_info)

        return PublishResult(
            publish_id=publish_id,
            status="PROCESSING_DOWNLOAD" if video_url else "PROCESSING_UPLOAD",
            mode="live", target=target, media="VIDEO",
            detail={"init": data, "source": source_info, "caption": caption[:MAX_TITLE]},
        )

    @staticmethod
    async def _upload_file(
        client: httpx.AsyncClient, upload_url: str, path: Path, source_info: dict
    ) -> None:
        size = source_info["video_size"]
        chunk_size = source_info["chunk_size"]
        total = source_info["total_chunk_count"]
        with path.open("rb") as handle:
            for index in range(total):
                start = index * chunk_size
                # The final chunk swallows the remainder (TikTok requirement).
                length = size - start if index == total - 1 else chunk_size
                handle.seek(start)
                blob = handle.read(length)
                headers = {
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(blob)),
                    "Content-Range": f"bytes {start}-{start + len(blob) - 1}/{size}",
                }
                put = await client.put(upload_url, headers=headers, content=blob, timeout=600.0)
                if put.status_code >= 400:
                    raise TikTokError(
                        f"chunk {index + 1}/{total} upload failed "
                        f"({put.status_code}): {put.text[:300]}"
                    )

    async def publish_photos(
        self, account: Account, photo_urls: list[str], title: str, caption: str, *,
        privacy_level: str = "SELF_ONLY", target: str = "DIRECT_POST", cover_index: int = 0,
    ) -> PublishResult:
        if not photo_urls:
            raise TikTokError("no photos to publish")
        body = {
            "media_type": "PHOTO",
            "post_mode": "DIRECT_POST" if target.upper() == "DIRECT_POST" else "MEDIA_UPLOAD",
            "post_info": {
                "title": title[:90],
                "description": caption[:MAX_TITLE],
                "privacy_level": privacy_level,
                "disable_comment": False,
                "auto_add_music": True,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "photo_cover_index": max(0, min(cover_index, len(photo_urls) - 1)),
                "photo_images": photo_urls[:35],
            },
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(CONTENT_INIT_URL, headers=self._headers(account), json=body)
            data = self._unwrap(response.json(), "content/init")
        return PublishResult(
            publish_id=data.get("publish_id", ""), status="PROCESSING_DOWNLOAD",
            mode="live", target=target, media="PHOTO",
            detail={"init": data, "photo_images": photo_urls},
        )

    async def fetch_status(self, account: Account, publish_id: str) -> dict:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                STATUS_URL, headers=self._headers(account), json={"publish_id": publish_id}
            )
        return self._unwrap(response.json(), "status/fetch")


def get_client(settings: Settings, account: Account | None = None) -> BaseTikTokClient:
    """Live client only when the app *and* the account are in live mode."""
    if settings.live_tiktok and (account is None or account.mode == "live"):
        return LiveTikTokClient(settings)
    return MockTikTokClient(settings)
