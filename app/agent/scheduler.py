"""Background worker that publishes scheduled jobs when their time comes."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from ..config import Settings, get_settings
from ..storage import Store, get_store
from .publisher import publish_job

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, settings: Settings | None = None, store: Store | None = None) -> None:
        self.s = settings or get_settings()
        self.store = store or get_store()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if not self.s.scheduler_enabled or self.running:
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._loop(), name="tiktok-scheduler")
        log.info("scheduler started (every %ss)", self.s.scheduler_interval_seconds)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - never kill the loop
                log.exception("scheduler tick failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.s.scheduler_interval_seconds
                )
            except asyncio.TimeoutError:
                continue

    async def tick(self) -> int:
        """Publish every job whose scheduled time has passed. Returns the count."""
        due = self.store.due_jobs()
        for job in due:
            log.info("publishing scheduled job %s", job.id)
            try:
                await publish_job(job.id, account_id=job.account_id,
                                  settings=self.s, store=self.store)
            except Exception as exc:  # noqa: BLE001
                log.warning("scheduled publish failed for %s: %s", job.id, exc)
        return len(due)


_scheduler: Scheduler | None = None


def get_scheduler() -> Scheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler
