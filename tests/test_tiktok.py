from __future__ import annotations

import pytest

from app.config import get_settings
from app.schemas import Account
from app.tiktok import MockTikTokClient, chunk_plan, get_client
from app.tiktok.client import LiveTikTokClient
from app.tiktok.oauth import build_authorize_url


def test_chunk_plan_small_file_is_single_chunk():
    size = 3 * 1024 * 1024
    assert chunk_plan(size) == (size, 1)


def test_chunk_plan_large_file_splits():
    size = 55 * 1024 * 1024
    chunk, total = chunk_plan(size)
    assert total == 5
    assert 5 * 1024 * 1024 <= chunk <= 64 * 1024 * 1024
    # The final chunk swallows the remainder, so everything is covered.
    assert chunk * (total - 1) < size


def test_chunk_plan_never_exceeds_1000_chunks():
    size = 20 * 1024 * 1024 * 1024
    _, total = chunk_plan(size)
    assert total <= 1000


async def test_mock_publish_video_roundtrip(tmp_path):
    settings = get_settings()
    client = MockTikTokClient(settings)
    account = Account(id="acc1", display_name="tester", mode="mock")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0" * 2048)

    result = await client.publish_video(account, video, "تجربة #اكسبلور")
    assert result.status == "PUBLISH_COMPLETE"
    assert result.publish_id.startswith("mock_")

    status = await client.fetch_status(account, result.publish_id)
    assert status["status"] == "PUBLISH_COMPLETE"
    assert status["caption"] == "تجربة #اكسبلور"


async def test_mock_publish_photos():
    client = MockTikTokClient(get_settings())
    account = Account(id="acc1", mode="mock")
    result = await client.publish_photos(
        account, ["https://x/1.jpg", "https://x/2.jpg"], "عنوان", "وصف"
    )
    assert result.media == "PHOTO"
    assert result.detail["photo_images"] == ["https://x/1.jpg", "https://x/2.jpg"]


def test_client_selection_defaults_to_mock():
    settings = get_settings()
    assert isinstance(get_client(settings), MockTikTokClient)


def test_client_selection_live(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "tiktok_mode", "live")
    monkeypatch.setattr(settings, "tiktok_client_key", "key")
    monkeypatch.setattr(settings, "tiktok_client_secret", "secret")
    account = Account(id="a", mode="live")
    assert isinstance(get_client(settings, account), LiveTikTokClient)


def test_authorize_url_contains_required_params(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "tiktok_client_key", "abc123")
    url = build_authorize_url(settings, "state-xyz")
    assert url.startswith("https://www.tiktok.com/v2/auth/authorize/")
    for part in ("client_key=abc123", "response_type=code", "state=state-xyz", "scope="):
        assert part in url


def test_live_client_raises_on_api_error():
    with pytest.raises(Exception):
        LiveTikTokClient._unwrap(
            {"error": {"code": "access_token_invalid", "message": "bad", "log_id": "1"}},
            "video/init",
        )
