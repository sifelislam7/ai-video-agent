from __future__ import annotations

from app.agent.pipeline import Pipeline, run_job
from app.providers.local import LocalTextProvider, estimate_duration
from app.schemas import ContentKind, CreateJobRequest, JobStatus


async def test_local_writer_returns_full_plan():
    brief = "TOPIC: الذكاء الاصطناعي\nLANGUAGE: ar\nSCENES: 4\nSTYLE: cinematic"
    raw = await LocalTextProvider().complete_json("sys", brief)
    assert len(raw["scenes"]) == 4
    assert raw["hook"]
    assert 5 <= len(raw["hashtags"]) <= 8
    assert all(not t.startswith("#") for t in raw["hashtags"])


def test_plan_normalisation_trims_and_fills():
    req = CreateJobRequest(topic="قهوة", scene_count=2, seconds=12)
    plan = Pipeline._normalise_plan(
        {
            "title": "t", "hook": "h", "caption": "c",
            "hashtags": ["#one", "two"],
            "scenes": [
                {"narration": "n1", "image_prompt": "p1"},
                {"narration": "n2", "image_prompt": "p2"},
                {"narration": "n3", "image_prompt": "p3"},
            ],
        },
        req,
    )
    assert len(plan.scenes) == 2  # respects scene_count
    assert plan.hashtags == ["one", "two"]
    assert plan.scenes[0].on_screen_text == "n1"  # falls back to narration
    assert "#one" in plan.full_caption


def test_plan_normalisation_survives_garbage():
    req = CreateJobRequest(topic="قهوة", scene_count=3, seconds=15)
    plan = Pipeline._normalise_plan({}, req)
    assert plan.scenes and plan.title


def test_estimate_duration_scales_with_length():
    short = estimate_duration("جملة قصيرة", "ar")
    long = estimate_duration("جملة قصيرة " * 12, "ar")
    assert 2.0 <= short < long <= 14.0


async def test_video_pipeline_end_to_end(store):
    """Full offline run: script ➜ images ➜ silence ➜ mp4."""
    req = CreateJobRequest(topic="فوائد المشي اليومي", scene_count=2, seconds=10,
                           voiceover=False, music=False)
    job = store.create_job(req)
    done = await run_job(job.id)

    assert done.status == JobStatus.READY, done.error
    assert done.result is not None
    assert done.result.video_path and done.result.video_path.endswith(".mp4")
    assert len(done.result.image_paths) == 2
    assert done.result.duration > 0
    from pathlib import Path

    assert Path(done.result.video_path).stat().st_size > 10_000
    assert Path(done.result.thumbnail_path).exists()


async def test_photo_pipeline_end_to_end(store):
    req = CreateJobRequest(topic="نصائح التصوير", kind=ContentKind.PHOTO,
                           scene_count=3, seconds=10, voiceover=False, music=False)
    job = store.create_job(req)
    done = await run_job(job.id)

    assert done.status == JobStatus.READY, done.error
    assert done.result.video_path is None
    assert len(done.result.image_paths) == 3
    from PIL import Image

    with Image.open(done.result.image_paths[0]) as img:
        assert img.size == (1080, 1350)
