"""TikTok OAuth 2.0 (v2) helpers.

Docs: https://developers.tiktok.com/doc/oauth-user-access-token-management
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from urllib.parse import urlencode

import httpx

from ..config import Settings
from ..schemas import Account
from ..storage import utcnow

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
REVOKE_URL = "https://open.tiktokapis.com/v2/oauth/revoke/"
USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"

DEFAULT_SCOPES = "user.info.basic,video.publish,video.upload"


class TikTokAuthError(RuntimeError):
    pass


def new_state() -> str:
    return secrets.token_urlsafe(24)


def build_authorize_url(settings: Settings, state: str, scopes: str = DEFAULT_SCOPES) -> str:
    if not settings.tiktok_client_key:
        raise TikTokAuthError("TIKTOK_CLIENT_KEY is not configured")
    params = {
        "client_key": settings.tiktok_client_key,
        "scope": scopes,
        "response_type": "code",
        "redirect_uri": settings.tiktok_redirect_uri,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(settings: Settings, code: str) -> dict:
    data = {
        "client_key": settings.tiktok_client_key,
        "client_secret": settings.tiktok_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": settings.tiktok_redirect_uri,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            TOKEN_URL, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    payload = response.json()
    if response.status_code >= 400 or payload.get("error"):
        raise TikTokAuthError(f"token exchange failed: {payload}")
    return payload


async def refresh_token(settings: Settings, refresh: str) -> dict:
    data = {
        "client_key": settings.tiktok_client_key,
        "client_secret": settings.tiktok_client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            TOKEN_URL, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    payload = response.json()
    if response.status_code >= 400 or payload.get("error"):
        raise TikTokAuthError(f"token refresh failed: {payload}")
    return payload


async def fetch_user_info(access_token: str) -> dict:
    fields = "open_id,union_id,avatar_url,display_name"
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(
            USER_INFO_URL,
            params={"fields": fields},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    payload = response.json()
    return payload.get("data", {}).get("user", {}) if response.status_code < 400 else {}


def account_from_token(payload: dict, user: dict | None = None) -> Account:
    user = user or {}
    expires_in = int(payload.get("expires_in") or 0)
    return Account(
        id=payload.get("open_id") or user.get("open_id") or secrets.token_hex(8),
        display_name=user.get("display_name") or "TikTok account",
        avatar_url=user.get("avatar_url", ""),
        access_token=payload.get("access_token", ""),
        refresh_token=payload.get("refresh_token", ""),
        expires_at=utcnow() + timedelta(seconds=expires_in) if expires_in else None,
        scopes=payload.get("scope", ""),
        mode="live",
        created_at=utcnow(),
    )


async def ensure_fresh(settings: Settings, account: Account) -> Account:
    """Refresh the access token when it is close to expiry."""
    if account.mode != "live" or not account.refresh_token:
        return account
    if account.expires_at and account.expires_at - utcnow() > timedelta(minutes=5):
        return account
    payload = await refresh_token(settings, account.refresh_token)
    account.access_token = payload.get("access_token", account.access_token)
    account.refresh_token = payload.get("refresh_token", account.refresh_token)
    expires_in = int(payload.get("expires_in") or 0)
    if expires_in:
        account.expires_at = utcnow() + timedelta(seconds=expires_in)
    return account
