"""Health + capability endpoints used by the dashboard."""

from __future__ import annotations

from fastapi import APIRouter

from .. import __version__
from ..agent.scheduler import get_scheduler
from ..config import get_settings
from ..media import ffmpeg, textkit
from ..providers import describe
from ..storage import get_store

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health() -> dict:
    store = get_store()
    try:
        ffmpeg_path = ffmpeg.ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        ffmpeg_path = f"unavailable: {exc}"
    return {
        "status": "ok",
        "version": __version__,
        "ffmpeg": ffmpeg_path,
        "jobs": len(store.list_jobs(limit=200)),
        "accounts": len(store.list_accounts()),
        "scheduler": get_scheduler().running,
    }


@router.get("/providers")
async def providers() -> dict:
    return describe(get_settings())


@router.get("/config")
async def config() -> dict:
    """Non-secret configuration, so the UI can show sane defaults."""
    s = get_settings()
    try:
        font = textkit.find_font(True)
    except Exception:  # noqa: BLE001
        font = ""
    return {
        "default_language": s.default_language,
        "default_scene_count": s.default_scene_count,
        "default_video_seconds": s.default_video_seconds,
        "video_size": [s.video_width, s.video_height],
        "fps": s.video_fps,
        "public_base_url": s.public_base_url,
        "arabic_font": font,
        "scheduler_enabled": s.scheduler_enabled,
    }
