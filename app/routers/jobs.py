"""Job endpoints: create content, follow progress, browse results."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ..agent.pipeline import run_job
from ..config import OUTPUT_DIR, get_settings
from ..schemas import CreateJobRequest, Job, JobStatus
from ..storage import get_store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_tasks: set[asyncio.Task] = set()


def _spawn(job_id: str) -> None:
    task = asyncio.create_task(run_job(job_id), name=f"job-{job_id}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _public(job: Job) -> dict:
    """Serialise a job, adding browser-friendly media URLs."""
    data = job.model_dump(mode="json")
    result = data.get("result") or {}
    if result:
        def to_url(path: str | None) -> str | None:
            if not path:
                return None
            name = Path(path).name
            return f"/media/{job.id}/{name}"

        result["video_url"] = to_url(result.get("video_path"))
        result["thumbnail_url"] = to_url(result.get("thumbnail_path"))
        result["audio_url"] = to_url(result.get("audio_path"))
        result["image_urls"] = [to_url(p) for p in result.get("image_paths", [])]
        data["result"] = result
    return data


@router.post("", status_code=201)
async def create_job(payload: CreateJobRequest) -> dict:
    settings = get_settings()
    payload.scene_count = min(payload.scene_count, 20)
    if not payload.language:
        payload.language = settings.default_language
    job = get_store().create_job(payload)
    _spawn(job.id)
    return _public(job)


@router.get("")
async def list_jobs(
    limit: int = Query(30, ge=1, le=200), status: JobStatus | None = None
) -> dict:
    jobs = get_store().list_jobs(limit=limit, status=status.value if status else None)
    return {"items": [_public(j) for j in jobs], "count": len(jobs)}


@router.get("/{job_id}")
async def get_job(job_id: str) -> dict:
    job = get_store().get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return _public(job)


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: str) -> None:
    store = get_store()
    if store.get_job(job_id) is None:
        raise HTTPException(404, "job not found")
    store.delete_job(job_id)
    folder = OUTPUT_DIR / job_id
    if folder.exists():
        for item in folder.iterdir():
            item.unlink(missing_ok=True)
        folder.rmdir()


@router.post("/{job_id}/retry")
async def retry_job(job_id: str) -> dict:
    store = get_store()
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    store.update_job(job_id, status=JobStatus.QUEUED, progress=0, step="queued", error=None)
    _spawn(job_id)
    return _public(store.get_job(job_id))  # type: ignore[arg-type]


@router.get("/{job_id}/download")
async def download(job_id: str) -> FileResponse:
    job = get_store().get_job(job_id)
    if job is None or job.result is None or not job.result.video_path:
        raise HTTPException(404, "no video for this job")
    path = Path(job.result.video_path)
    if not path.exists():
        raise HTTPException(404, "file missing on disk")
    return FileResponse(path, media_type="video/mp4", filename=f"{job_id}.mp4")
