"""Publishing step: hand a finished job to TikTok (live or mock)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from urllib.parse import quote

from ..config import OUTPUT_DIR, Settings, get_settings
from ..schemas import Account, JobStatus
from ..storage import Store, get_store, utcnow
from ..tiktok import get_client
from ..tiktok.oauth import ensure_fresh

log = logging.getLogger(__name__)

MOCK_ACCOUNT_ID = "mock_account"


def ensure_account(store: Store, account_id: str | None = None) -> Account:
    """Return the requested account, creating the mock one when needed."""
    account = store.get_account(account_id)
    if account:
        return account
    return store.upsert_account(Account(
        id=MOCK_ACCOUNT_ID, display_name="حساب تجريبي (Mock)", mode="mock",
        scopes="user.info.basic,video.publish", created_at=utcnow(),
    ))


def media_url(settings: Settings, job_id: str, filename: str) -> str:
    base = settings.public_base_url.rstrip("/")
    return f"{base}/media/{quote(job_id)}/{quote(filename)}"


async def publish_job(
    job_id: str,
    *,
    account_id: str | None = None,
    caption: str | None = None,
    privacy_level: str | None = None,
    target: str | None = None,
    settings: Settings | None = None,
    store: Store | None = None,
) -> dict:
    s = settings or get_settings()
    store = store or get_store()
    job = store.get_job(job_id)
    if job is None:
        raise ValueError(f"unknown job {job_id}")
    if job.result is None:
        raise ValueError("job has no generated media yet")

    account = ensure_account(store, account_id or job.account_id)
    if account.mode == "live":
        account = await ensure_fresh(s, account)
        store.upsert_account(account)

    client = get_client(s, account)
    privacy = privacy_level or job.request.privacy_level or s.tiktok_privacy_level
    post_target = (target or s.tiktok_post_target).upper()
    text = caption or (job.result.plan.full_caption if job.result.plan else job.request.topic)

    store.update_job(job_id, status=JobStatus.PUBLISHING, step="publishing",
                     account_id=account.id)
    store.append_log(job_id, "publish",
                     f"النشر عبر «{client.mode}» إلى {account.display_name or account.id}")

    try:
        if job.result.kind.value == "photo" or not job.result.video_path:
            urls = [
                media_url(s, job_id, Path(p).name) for p in job.result.image_paths
            ]
            result = await client.publish_photos(
                account, urls, job.result.plan.title if job.result.plan else "", text,
                privacy_level=privacy, target=post_target,
            )
        else:
            video_path = Path(job.result.video_path)
            video_url = (
                media_url(s, job_id, video_path.name)
                if s.tiktok_upload_source.upper() == "PULL_FROM_URL" else None
            )
            result = await client.publish_video(
                account, video_path, text, privacy_level=privacy,
                target=post_target, video_url=video_url,
            )

        payload = result.dict()
        # Poll for the final state (TikTok processes asynchronously).
        if client.mode == "live" and result.publish_id:
            payload["status_history"] = await _poll(client, account, result.publish_id, store, job_id)
            payload["status"] = payload["status_history"][-1].get("status", result.status)

        updated = job.result.model_copy(update={"publish": payload})
        final = (
            JobStatus.PUBLISHED
            if payload["status"] in {"PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"}
            else JobStatus.PUBLISHING
        )
        store.update_job(job_id, result=updated, status=final, step="published",
                         scheduled_at=None, error=None)
        store.append_log(job_id, "publish",
                         f"✅ {payload['status']} — publish_id={payload['publish_id']}")
        return payload
    except Exception as exc:  # noqa: BLE001
        log.exception("publishing job %s failed", job_id)
        store.update_job(job_id, status=JobStatus.FAILED, error=str(exc), step="publish failed")
        store.append_log(job_id, "publish", f"❌ {exc}", level="error")
        raise


async def _poll(client, account: Account, publish_id: str, store: Store, job_id: str,
                attempts: int = 10, delay: float = 3.0) -> list[dict]:
    history: list[dict] = []
    for attempt in range(attempts):
        await asyncio.sleep(delay if attempt else 1.0)
        try:
            status = await client.fetch_status(account, publish_id)
        except Exception as exc:  # noqa: BLE001
            history.append({"status": "UNKNOWN", "error": str(exc)})
            break
        history.append(status)
        state = status.get("status")
        store.append_log(job_id, "publish", f"حالة النشر: {state}")
        if state in {"PUBLISH_COMPLETE", "FAILED", "SEND_TO_USER_INBOX"}:
            break
    return history or [{"status": "PROCESSING_UPLOAD"}]


def job_media_dir(job_id: str) -> Path:
    return OUTPUT_DIR / job_id
