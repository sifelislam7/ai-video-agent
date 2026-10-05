"""Central configuration, loaded from environment / .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
ASSETS_DIR = ROOT_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
MUSIC_DIR = ASSETS_DIR / "music"
OUTPUT_DIR = DATA_DIR / "output"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- server ----
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    public_base_url: str = "http://localhost:8000"

    # ---- provider selection ----
    text_provider: str = "auto"
    image_provider: str = "auto"
    tts_provider: str = "auto"
    video_provider: str = "auto"

    # ---- openai ----
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_text_model: str = "gpt-4o-mini"
    openai_image_model: str = "gpt-image-1"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"

    # ---- gemini ----
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_text_model: str = "gemini-2.0-flash"
    gemini_image_model: str = "gemini-2.0-flash-preview-image-generation"

    # ---- openrouter ----
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_text_model: str = "openai/gpt-4o-mini"

    # ---- elevenlabs ----
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_model: str = "eleven_multilingual_v2"

    # ---- replicate ----
    replicate_api_token: str = ""
    replicate_image_model: str = "black-forest-labs/flux-schnell"
    replicate_video_model: str = ""

    # ---- tiktok ----
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_redirect_uri: str = "http://localhost:8000/api/tiktok/callback"
    tiktok_mode: str = "mock"  # mock | live
    tiktok_upload_source: str = "FILE_UPLOAD"  # FILE_UPLOAD | PULL_FROM_URL
    tiktok_post_target: str = "DIRECT_POST"  # DIRECT_POST | INBOX
    tiktok_privacy_level: str = "SELF_ONLY"

    # ---- agent defaults ----
    default_language: str = "ar"
    default_scene_count: int = 5
    default_video_seconds: int = 30
    video_width: int = 1080
    video_height: int = 1920
    video_fps: int = 30

    # ---- scheduler ----
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 30

    # ---------------------------------------------------------------- helpers
    @property
    def tiktok_configured(self) -> bool:
        return bool(self.tiktok_client_key and self.tiktok_client_secret)

    @property
    def live_tiktok(self) -> bool:
        return self.tiktok_mode.lower() == "live" and self.tiktok_configured

    def ensure_dirs(self) -> None:
        for d in (DATA_DIR, OUTPUT_DIR, ASSETS_DIR, FONTS_DIR, MUSIC_DIR):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


settings = get_settings()
