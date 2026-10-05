"""TikTok endpoints: OAuth connect, accounts, publishing and scheduling."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from ..agent.publisher import ensure_account, publish_job
from ..config import get_settings
from ..schemas import Account, JobStatus, PublishRequest, ScheduleRequest
from ..storage import get_store, utcnow
from ..tiktok import get_client
from ..tiktok.oauth import (
    DEFAULT_SCOPES,
    TikTokAuthError,
    account_from_token,
    build_authorize_url,
    exchange_code,
    fetch_user_info,
    new_state,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tiktok", tags=["tiktok"])

# state -> created_at (CSRF protection for the OAuth round-trip)
_states: dict[str, float] = {}
_STATE_TTL = 600


def _remember(state: str) -> None:
    now = time.time()
    for key, created in list(_states.items()):
        if now - created > _STATE_TTL:
            _states.pop(key, None)
    _states[state] = now


@router.get("/status")
async def status() -> dict:
    s = get_settings()
    accounts = get_store().list_accounts()
    return {
        "mode": "live" if s.live_tiktok else "mock",
        "configured": s.tiktok_configured,
        "redirect_uri": s.tiktok_redirect_uri,
        "scopes": DEFAULT_SCOPES,
        "upload_source": s.tiktok_upload_source,
        "post_target": s.tiktok_post_target,
        "privacy_level": s.tiktok_privacy_level,
        "accounts": [a.public() for a in accounts],
    }


@router.get("/accounts")
async def accounts() -> dict:
    return {"items": [a.public() for a in get_store().list_accounts()]}


@router.post("/accounts/mock", status_code=201)
async def create_mock_account() -> dict:
    account = ensure_account(get_store())
    return account.public()


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(account_id: str) -> None:
    get_store().delete_account(account_id)


@router.get("/auth")
async def auth() -> RedirectResponse:
    s = get_settings()
    if not s.tiktok_configured:
        raise HTTPException(
            400, "TikTok is not configured — set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET"
        )
    state = new_state()
    _remember(state)
    return RedirectResponse(build_authorize_url(s, state), status_code=302)


@router.get("/callback", response_class=HTMLResponse)
async def callback(
    code: str | None = None, state: str | None = None, error: str | None = None,
    error_description: str | None = None,
) -> HTMLResponse:
    if error:
        return HTMLResponse(_page("فشل الربط", f"{error}: {error_description or ''}"), 400)
    if not code:
        return HTMLResponse(_page("فشل الربط", "لم يصل رمز التفويض (code)"), 400)
    if not state or state not in _states:
        return HTMLResponse(_page("فشل الربط", "state غير صالح أو منتهي الصلاحية"), 400)
    _states.pop(state, None)

    s = get_settings()
    try:
        payload = await exchange_code(s, code)
        user = await fetch_user_info(payload.get("access_token", ""))
        account = account_from_token(payload, user)
        get_store().upsert_account(account)
    except TikTokAuthError as exc:
        return HTMLResponse(_page("فشل الربط", str(exc)), 400)
    return HTMLResponse(
        _page("تم ربط الحساب ✅", f"الحساب: {account.display_name or account.id}", home=True)
    )


@router.get("/creator-info")
async def creator_info(account_id: str | None = Query(None)) -> dict:
    s = get_settings()
    account = ensure_account(get_store(), account_id)
    client = get_client(s, account)
    return await client.creator_info(account)


@router.post("/publish")
async def publish(payload: PublishRequest) -> dict:
    try:
        return await publish_job(
            payload.job_id, account_id=payload.account_id, caption=payload.caption,
            privacy_level=payload.privacy_level, target=payload.target,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc)) from exc


@router.post("/schedule")
async def schedule(payload: ScheduleRequest) -> dict:
    store = get_store()
    job = store.get_job(payload.job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if job.result is None:
        raise HTTPException(409, "job has no media yet")
    when = payload.publish_at
    if when.tzinfo is None:
        when = when.replace(tzinfo=utcnow().tzinfo)
    store.update_job(payload.job_id, status=JobStatus.SCHEDULED, scheduled_at=when,
                     step="scheduled", account_id=payload.account_id)
    store.append_log(payload.job_id, "schedule", f"مجدول للنشر في {when.isoformat()}")
    return {"job_id": payload.job_id, "scheduled_at": when.isoformat(), "status": "scheduled"}


def _page(title: str, message: str, home: bool = False) -> str:
    link = '<a href="/">العودة إلى لوحة التحكم</a>' if home else ""
    return f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<title>{title}</title><style>
body{{font-family:system-ui,-apple-system,Segoe UI,Tahoma,sans-serif;background:#0b0d17;
color:#eef1ff;display:grid;place-items:center;height:100vh;margin:0;text-align:center}}
.card{{background:#161a2c;padding:40px 56px;border-radius:20px;border:1px solid #2a3050}}
a{{color:#7df0c4}}</style></head><body><div class="card"><h1>{title}</h1>
<p>{message}</p>{link}</div></body></html>"""
