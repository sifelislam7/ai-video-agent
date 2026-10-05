from __future__ import annotations

from datetime import timedelta

from app.agent.pipeline import run_job
from app.agent.scheduler import Scheduler
from app.schemas import CreateJobRequest, JobStatus
from app.storage import utcnow


async def test_due_jobs_are_published_by_the_scheduler(store):
    req = CreateJobRequest(topic="جدولة تلقائية", scene_count=1, seconds=6,
                           voiceover=False, music=False)
    job = store.create_job(req)
    await run_job(job.id)

    store.update_job(job.id, status=JobStatus.SCHEDULED,
                     scheduled_at=utcnow() - timedelta(minutes=1))
    assert [j.id for j in store.due_jobs()] == [job.id]

    published = await Scheduler(store=store).tick()
    assert published == 1
    assert store.get_job(job.id).status == JobStatus.PUBLISHED


async def test_future_jobs_are_not_due(store):
    req = CreateJobRequest(topic="لاحقًا", scene_count=1, seconds=6,
                           voiceover=False, music=False)
    job = store.create_job(req)
    store.update_job(job.id, status=JobStatus.SCHEDULED,
                     scheduled_at=utcnow() + timedelta(hours=2))
    assert store.due_jobs() == []


async def test_due_check_handles_non_utc_offsets(store):
    """Scheduled times are normalised to UTC before they are compared."""
    from datetime import timezone

    req = CreateJobRequest(topic="توقيت محلي", scene_count=1, seconds=6,
                           voiceover=False, music=False)
    job = store.create_job(req)
    local = (utcnow() - timedelta(minutes=5)).astimezone(timezone(timedelta(hours=5)))
    store.update_job(job.id, status=JobStatus.SCHEDULED, scheduled_at=local)
    assert [j.id for j in store.due_jobs()] == [job.id]
