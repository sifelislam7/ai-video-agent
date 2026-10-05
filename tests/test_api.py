from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.main import app
from app.schemas import CreateJobRequest


def wait_for(client: TestClient, job_id: str, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"ready", "published", "failed", "scheduled"}:
            return job
        time.sleep(0.5)
    raise AssertionError("job did not finish in time")


def test_health_and_providers():
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["status"] == "ok"
        assert "ffmpeg" in health

        providers = client.get("/api/providers").json()
        for kind in ("text", "image", "tts"):
            assert providers[kind]["selected"]
        assert providers["tiktok"]["mode"] in {"mock", "live"}


def test_dashboard_served():
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "وكيل المحتوى الذكي" in page.text


def test_create_job_validation():
    with TestClient(app) as client:
        assert client.post("/api/jobs", json={"topic": "x"}).status_code == 422
        assert client.post("/api/jobs", json={}).status_code == 422


def test_full_flow_create_then_publish_mock():
    payload = CreateJobRequest(
        topic="ثلاث نصائح للإنتاجية", scene_count=2, seconds=10,
        voiceover=False, music=False,
    ).model_dump(mode="json")

    with TestClient(app) as client:
        created = client.post("/api/jobs", json=payload)
        assert created.status_code == 201
        job_id = created.json()["id"]

        job = wait_for(client, job_id)
        assert job["status"] == "ready", job.get("error")
        assert job["result"]["video_url"].startswith(f"/media/{job_id}/")

        listing = client.get("/api/jobs").json()
        assert any(item["id"] == job_id for item in listing["items"])

        # mock account + publish
        account = client.post("/api/tiktok/accounts/mock")
        assert account.status_code == 201

        published = client.post("/api/tiktok/publish", json={"job_id": job_id})
        assert published.status_code == 200, published.text
        body = published.json()
        assert body["mode"] == "mock"
        assert body["status"] == "PUBLISH_COMPLETE"

        after = client.get(f"/api/jobs/{job_id}").json()
        assert after["status"] == "published"

        assert client.get(f"/api/jobs/{job_id}/download").status_code == 200
        assert client.delete(f"/api/jobs/{job_id}").status_code == 204
        assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_schedule_endpoint_marks_job():
    payload = CreateJobRequest(topic="تجربة الجدولة", scene_count=1, seconds=6,
                               voiceover=False, music=False).model_dump(mode="json")
    with TestClient(app) as client:
        job_id = client.post("/api/jobs", json=payload).json()["id"]
        wait_for(client, job_id)
        response = client.post("/api/tiktok/schedule", json={
            "job_id": job_id, "publish_at": "2099-01-01T10:00:00+00:00",
        })
        assert response.status_code == 200
        assert client.get(f"/api/jobs/{job_id}").json()["status"] == "scheduled"


def test_tiktok_status_endpoint():
    with TestClient(app) as client:
        body = client.get("/api/tiktok/status").json()
        assert body["mode"] in {"mock", "live"}
        assert "redirect_uri" in body
        assert client.get("/api/tiktok/auth").status_code in {400, 302, 307}
