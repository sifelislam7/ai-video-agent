"""Pydantic request/response models shared by the API and the agent."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ContentKind(str, Enum):
    VIDEO = "video"
    PHOTO = "photo"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"  # media generated, awaiting review / publish
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    SCHEDULED = "scheduled"


class VisualStyle(str, Enum):
    CINEMATIC = "cinematic"
    ANIME = "anime"
    PHOTOREAL = "photoreal"
    MINIMAL = "minimal"
    THREE_D = "3d"
    RETRO = "retro"


class Scene(BaseModel):
    index: int
    narration: str = ""
    on_screen_text: str = ""
    image_prompt: str = ""
    seconds: float = 5.0
    image_path: str | None = None
    audio_path: str | None = None


class ContentPlan(BaseModel):
    """What the writer model returns, normalised."""

    title: str = ""
    hook: str = ""
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    music_mood: str = "upbeat"
    language: str = "ar"

    @property
    def full_caption(self) -> str:
        tags = " ".join(f"#{t.lstrip('#')}" for t in self.hashtags)
        return (self.caption + ("\n" + tags if tags else "")).strip()


class CreateJobRequest(BaseModel):
    topic: str = Field(..., min_length=2, description="موضوع المحتوى / content topic")
    kind: ContentKind = ContentKind.VIDEO
    language: str = "ar"
    style: VisualStyle = VisualStyle.CINEMATIC
    scene_count: int = Field(5, ge=1, le=20)
    seconds: int = Field(30, ge=5, le=180)
    voiceover: bool = True
    captions: bool = True
    music: bool = True
    audience: str = ""
    extra_instructions: str = ""
    # publishing
    auto_publish: bool = False
    schedule_at: datetime | None = None
    privacy_level: str | None = None


class PublishRequest(BaseModel):
    job_id: str
    account_id: str | None = None
    privacy_level: str | None = None
    caption: str | None = None
    target: Literal["DIRECT_POST", "INBOX"] | None = None


class ScheduleRequest(BaseModel):
    job_id: str
    publish_at: datetime
    account_id: str | None = None


class LogEntry(BaseModel):
    at: datetime
    level: str = "info"
    step: str = ""
    message: str = ""


class JobResult(BaseModel):
    kind: ContentKind = ContentKind.VIDEO
    video_path: str | None = None
    image_paths: list[str] = Field(default_factory=list)
    audio_path: str | None = None
    thumbnail_path: str | None = None
    duration: float = 0.0
    plan: ContentPlan | None = None
    providers: dict[str, str] = Field(default_factory=dict)
    publish: dict[str, Any] = Field(default_factory=dict)


class Job(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    status: JobStatus
    progress: int = 0
    step: str = ""
    request: CreateJobRequest
    result: JobResult | None = None
    logs: list[LogEntry] = Field(default_factory=list)
    error: str | None = None
    scheduled_at: datetime | None = None
    account_id: str | None = None


class Account(BaseModel):
    id: str
    display_name: str = ""
    avatar_url: str = ""
    access_token: str = ""
    refresh_token: str = ""
    expires_at: datetime | None = None
    scopes: str = ""
    mode: str = "mock"
    created_at: datetime | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "scopes": self.scopes,
            "mode": self.mode,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
