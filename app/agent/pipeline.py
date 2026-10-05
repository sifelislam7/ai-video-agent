"""The content agent: brief ➜ script ➜ images ➜ voice ➜ video ➜ publish."""

from __future__ import annotations

import asyncio
import io
import logging
import random
from pathlib import Path

from PIL import Image

from ..config import MUSIC_DIR, OUTPUT_DIR, Settings, get_settings
from ..media import ffmpeg, imagekit
from ..providers import ProviderError, resolve_image, resolve_text, resolve_tts
from ..providers.local import LocalImageProvider, estimate_duration
from ..schemas import (
    ContentKind,
    ContentPlan,
    CreateJobRequest,
    Job,
    JobResult,
    JobStatus,
    Scene,
)
from ..storage import Store, get_store
from . import prompts

log = logging.getLogger(__name__)

PHOTO_SIZE = (1080, 1350)


class Pipeline:
    def __init__(self, settings: Settings | None = None, store: Store | None = None) -> None:
        self.s = settings or get_settings()
        self.store = store or get_store()

    # ------------------------------------------------------------------ util
    def _log(self, job_id: str, step: str, message: str, level: str = "info") -> None:
        self.store.append_log(job_id, step, message, level)
        log.info("[%s] %s — %s", job_id, step, message)

    def _progress(self, job_id: str, progress: int, step: str) -> None:
        self.store.update_job(job_id, progress=progress, step=step)

    # ------------------------------------------------------------------- run
    async def run(self, job_id: str) -> Job:
        job = self.store.get_job(job_id)
        if job is None:
            raise ValueError(f"unknown job {job_id}")
        req = job.request
        workdir = OUTPUT_DIR / job_id
        workdir.mkdir(parents=True, exist_ok=True)

        self.store.update_job(job_id, status=JobStatus.RUNNING, progress=2, step="starting")
        providers: dict[str, str] = {}
        try:
            # 1 ─ script ------------------------------------------------------
            self._progress(job_id, 5, "writing script")
            plan, text_provider = await self._write_plan(job_id, req)
            providers["text"] = text_provider
            self._log(job_id, "script", f"«{plan.hook or plan.title}» — {len(plan.scenes)} مشهد")

            # 2 ─ visuals -----------------------------------------------------
            image_provider = resolve_image(self.s)
            providers["image"] = image_provider.name
            self._progress(job_id, 20, "generating visuals")
            is_photo = req.kind == ContentKind.PHOTO
            size = PHOTO_SIZE if is_photo else (self.s.video_width, self.s.video_height)
            await self._make_images(job_id, req, plan, workdir, size, is_photo)

            result = JobResult(kind=req.kind, plan=plan, providers=providers)
            result.image_paths = [s.image_path for s in plan.scenes if s.image_path]

            if is_photo:
                result.thumbnail_path = result.image_paths[0] if result.image_paths else None
                result.duration = 0.0
                self._progress(job_id, 95, "finalising carousel")
            else:
                # 3 ─ voice ---------------------------------------------------
                voice_track: Path | None = None
                if req.voiceover:
                    tts = resolve_tts(self.s)
                    providers["tts"] = tts.name
                    self._progress(job_id, 55, "recording voiceover")
                    voice_track = await self._make_voice(job_id, req, plan, workdir)
                else:
                    per_scene = max(req.seconds / max(len(plan.scenes), 1), 2.0)
                    for scene in plan.scenes:
                        scene.seconds = per_scene

                # 4 ─ assembly ------------------------------------------------
                self._progress(job_id, 70, "assembling video")
                video_path, duration, audio_path = await self._assemble(
                    job_id, req, plan, workdir, voice_track
                )
                result.video_path = str(video_path)
                result.audio_path = str(audio_path) if audio_path else None
                result.duration = duration
                thumb = workdir / "thumbnail.jpg"
                await asyncio.to_thread(
                    ffmpeg.extract_thumbnail, video_path, thumb, min(1.0, duration / 3)
                )
                result.thumbnail_path = str(thumb)
                self._progress(job_id, 92, "video ready")

            self.store.update_job(job_id, result=result, status=JobStatus.READY,
                                  progress=100, step="ready", error=None)
            self._log(job_id, "done", "المحتوى جاهز ✅")

            # 5 ─ publishing --------------------------------------------------
            if req.schedule_at:
                self.store.update_job(job_id, status=JobStatus.SCHEDULED,
                                      scheduled_at=req.schedule_at, step="scheduled")
                self._log(job_id, "schedule",
                          f"تمت جدولة النشر في {req.schedule_at.isoformat()}")
            elif req.auto_publish:
                from .publisher import publish_job  # local import avoids a cycle

                await publish_job(job_id, settings=self.s, store=self.store)

        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            log.exception("job %s failed", job_id)
            self.store.update_job(job_id, status=JobStatus.FAILED, error=str(exc), step="failed")
            self._log(job_id, "error", str(exc), level="error")

        return self.store.get_job(job_id)  # type: ignore[return-value]

    # ---------------------------------------------------------------- script
    async def _write_plan(self, job_id: str, req: CreateJobRequest) -> tuple[ContentPlan, str]:
        provider = resolve_text(self.s)
        brief = prompts.build_brief(req)
        try:
            raw = await provider.complete_json(prompts.SYSTEM, brief, temperature=0.85)
            used = provider.name
        except ProviderError as exc:
            self._log(job_id, "script", f"{provider.name} فشل ({exc}) — التحويل إلى الكاتب المحلي",
                      level="warning")
            from ..providers.local import LocalTextProvider

            raw = await LocalTextProvider().complete_json(prompts.SYSTEM, brief)
            used = "local"
        return self._normalise_plan(raw, req), used

    @staticmethod
    def _normalise_plan(raw: dict, req: CreateJobRequest) -> ContentPlan:
        scenes_raw = raw.get("scenes") or []
        scenes: list[Scene] = []
        for i, item in enumerate(scenes_raw[: req.scene_count]):
            if isinstance(item, str):
                item = {"narration": item}
            narration = str(item.get("narration") or item.get("text") or "").strip()
            scenes.append(Scene(
                index=i,
                narration=narration,
                on_screen_text=str(item.get("on_screen_text") or narration)[:120].strip(),
                image_prompt=str(
                    item.get("image_prompt") or item.get("visual") or req.topic
                ).strip(),
                seconds=max(req.seconds / max(req.scene_count, 1), 2.0),
            ))
        if not scenes:
            scenes = [Scene(index=0, narration=req.topic, on_screen_text=req.topic,
                            image_prompt=req.topic, seconds=float(req.seconds))]
        hashtags = [str(t).lstrip("#").strip() for t in (raw.get("hashtags") or []) if str(t).strip()]
        return ContentPlan(
            title=str(raw.get("title") or req.topic)[:120],
            hook=str(raw.get("hook") or scenes[0].on_screen_text)[:160],
            caption=str(raw.get("caption") or raw.get("title") or req.topic)[:1500],
            hashtags=hashtags[:8],
            scenes=scenes,
            music_mood=str(raw.get("music_mood") or "upbeat").lower(),
            language=req.language,
        )

    # ---------------------------------------------------------------- images
    async def _make_images(
        self, job_id: str, req: CreateJobRequest, plan: ContentPlan,
        workdir: Path, size: tuple[int, int], is_photo: bool,
    ) -> None:
        provider = resolve_image(self.s)
        fallback = LocalImageProvider()
        total = len(plan.scenes)
        for scene in plan.scenes:
            prompt = scene.image_prompt or plan.title
            try:
                raw = await provider.generate(
                    prompt, width=size[0], height=size[1], style=req.style.value
                )
                base = Image.open(io.BytesIO(raw))
            except Exception as exc:  # noqa: BLE001
                if provider.name != "local":
                    self._log(job_id, "image",
                              f"{provider.name} فشل في المشهد {scene.index + 1}: {exc} — رسم محلي",
                              level="warning")
                raw = await fallback.generate(
                    prompt, width=size[0], height=size[1], style=req.style.value
                )
                base = Image.open(io.BytesIO(raw))

            def _compose(base_img: Image.Image = base, sc: Scene = scene) -> Path:
                if is_photo:
                    card = imagekit.compose_photo_card(
                        base_img, size=size,
                        title=sc.on_screen_text if sc.index else (plan.hook or plan.title),
                        body=sc.narration if sc.index else "",
                        index=sc.index, total=total,
                    )
                else:
                    card = imagekit.compose_scene(
                        base_img, size=size,
                        headline=plan.hook if sc.index == 0 else "",
                        caption=sc.on_screen_text if req.captions else "",
                        index=sc.index, total=total,
                    )
                return imagekit.save(card, workdir / f"scene_{sc.index + 1:02d}.jpg")

            path = await asyncio.to_thread(_compose)
            scene.image_path = str(path)
            self._progress(
                job_id, 20 + int(30 * (scene.index + 1) / total),
                f"visual {scene.index + 1}/{total}",
            )
        self._log(job_id, "image", f"تم إنشاء {total} صورة عبر «{provider.name}»")

    # ----------------------------------------------------------------- voice
    async def _make_voice(
        self, job_id: str, req: CreateJobRequest, plan: ContentPlan, workdir: Path
    ) -> Path | None:
        tts = resolve_tts(self.s)
        from ..providers.local import LocalTTSProvider

        fallback = LocalTTSProvider()
        segments: list[tuple[Path, float]] = []
        total = len(plan.scenes)
        for scene in plan.scenes:
            text = scene.narration or scene.on_screen_text
            if not text:
                continue
            try:
                audio = await tts.synthesize(text, language=req.language)
                suffix = ".mp3" if tts.name != "local" else ".wav"
            except Exception as exc:  # noqa: BLE001
                self._log(job_id, "tts", f"{tts.name} فشل: {exc} — صمت موقوت بدلاً منه",
                          level="warning")
                audio = await fallback.synthesize(text, language=req.language)
                suffix = ".wav"
            path = workdir / f"voice_{scene.index + 1:02d}{suffix}"
            path.write_bytes(audio)
            duration = await asyncio.to_thread(ffmpeg.probe_duration, path)
            if duration <= 0.1:
                duration = estimate_duration(text, req.language)
            scene.seconds = round(duration + 0.45, 2)
            scene.audio_path = str(path)
            segments.append((path, scene.seconds))
            self._progress(
                job_id, 55 + int(12 * (scene.index + 1) / total),
                f"voice {scene.index + 1}/{total}",
            )
        if not segments:
            return None
        track = workdir / "voice.wav"
        await asyncio.to_thread(ffmpeg.concat_audio, [(p, d) for p, d in segments], track)
        self._log(job_id, "tts", f"تم تسجيل التعليق الصوتي عبر «{tts.name}»")
        return track

    # -------------------------------------------------------------- assembly
    async def _assemble(
        self, job_id: str, req: CreateJobRequest, plan: ContentPlan,
        workdir: Path, voice: Path | None,
    ) -> tuple[Path, float, Path | None]:
        clips: list[Path] = []
        total = len(plan.scenes)
        for scene in plan.scenes:
            if not scene.image_path:
                continue
            clip = workdir / f"clip_{scene.index + 1:02d}.mp4"
            await asyncio.to_thread(
                ffmpeg.still_to_clip, scene.image_path, clip, scene.seconds,
                self.s.video_width, self.s.video_height, self.s.video_fps,
                zoom_in=scene.index % 2 == 0,
            )
            clips.append(clip)
            self._progress(job_id, 70 + int(15 * (scene.index + 1) / total),
                           f"clip {scene.index + 1}/{total}")

        silent = workdir / "silent.mp4"
        await asyncio.to_thread(ffmpeg.concat_clips, clips, silent, workdir)
        duration = sum(s.seconds for s in plan.scenes if s.image_path)

        music: Path | None = None
        if req.music:
            music = await asyncio.to_thread(self._music_bed, plan, workdir, duration)
            if music:
                self._log(job_id, "music", f"موسيقى خلفية ({plan.music_mood})")

        audio: Path | None = None
        if voice or music:
            audio = workdir / "mix.wav"
            await asyncio.to_thread(ffmpeg.mix_audio, voice, music, audio, duration)

        output = workdir / "video.mp4"
        await asyncio.to_thread(ffmpeg.mux, silent, audio, output)
        for clip in clips:
            clip.unlink(missing_ok=True)
        silent.unlink(missing_ok=True)
        return output, round(duration, 2), audio

    def _music_bed(self, plan: ContentPlan, workdir: Path, duration: float) -> Path | None:
        """Pick a user-supplied track, otherwise synthesize a soft pad."""
        tracks = sorted(
            p for p in MUSIC_DIR.glob("*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg"}
        )
        if tracks:
            return random.Random(plan.title).choice(tracks)
        try:
            return ffmpeg.make_ambient_bed(duration, workdir / "music.wav", plan.music_mood)
        except Exception as exc:  # noqa: BLE001
            log.warning("ambient bed failed: %s", exc)
            return None


async def run_job(job_id: str, settings: Settings | None = None, store: Store | None = None) -> Job:
    return await Pipeline(settings, store).run(job_id)
