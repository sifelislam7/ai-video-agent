"""Command line interface — useful for cron jobs and quick tests.

    python -m app.cli create --topic "٣ عادات صباحية" --scenes 4 --publish
    python -m app.cli list
    python -m app.cli publish <job_id>
    python -m app.cli serve
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime

from .agent.pipeline import run_job
from .agent.publisher import publish_job
from .config import get_settings
from .providers import describe
from .schemas import ContentKind, CreateJobRequest, VisualStyle
from .storage import get_store


async def _create(args: argparse.Namespace) -> int:
    store = get_store()
    req = CreateJobRequest(
        topic=args.topic,
        kind=ContentKind(args.kind),
        language=args.language,
        style=VisualStyle(args.style),
        scene_count=args.scenes,
        seconds=args.seconds,
        voiceover=not args.no_voice,
        captions=not args.no_captions,
        music=not args.no_music,
        audience=args.audience or "",
        extra_instructions=args.instructions or "",
        auto_publish=args.publish,
        schedule_at=datetime.fromisoformat(args.schedule) if args.schedule else None,
        privacy_level=args.privacy,
    )
    job = store.create_job(req)
    print(f"▶ job {job.id} — {req.topic}")
    done = await run_job(job.id)
    print(f"  status: {done.status.value}")
    if done.error:
        print(f"  error : {done.error}", file=sys.stderr)
        return 1
    if done.result:
        if done.result.video_path:
            print(f"  video : {done.result.video_path} ({done.result.duration}s)")
        for path in done.result.image_paths:
            print(f"  image : {path}")
        if done.result.plan:
            print(f"  caption:\n{done.result.plan.full_caption}")
        if done.result.publish:
            print(f"  publish: {json.dumps(done.result.publish, ensure_ascii=False)[:400]}")
    return 0


async def _publish(args: argparse.Namespace) -> int:
    payload = await publish_job(args.job_id, account_id=args.account)
    print(json.dumps(payload, ensure_ascii=False, indent=2)[:1200])
    return 0


def _list(args: argparse.Namespace) -> int:
    for job in get_store().list_jobs(limit=args.limit):
        title = job.result.plan.title if job.result and job.result.plan else job.request.topic
        print(f"{job.id}  {job.status.value:<10} {job.created_at:%Y-%m-%d %H:%M}  {title}")
    return 0


def _providers(_: argparse.Namespace) -> int:
    print(json.dumps(describe(get_settings()), ensure_ascii=False, indent=2))
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=args.host or settings.app_host,
                port=args.port or settings.app_port, reload=args.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-video-agent", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="generate content (and optionally publish)")
    create.add_argument("--topic", required=True)
    create.add_argument("--kind", default="video", choices=[k.value for k in ContentKind])
    create.add_argument("--language", default=get_settings().default_language)
    create.add_argument("--style", default="cinematic", choices=[s.value for s in VisualStyle])
    create.add_argument("--scenes", type=int, default=get_settings().default_scene_count)
    create.add_argument("--seconds", type=int, default=get_settings().default_video_seconds)
    create.add_argument("--audience", default="")
    create.add_argument("--instructions", default="")
    create.add_argument("--privacy", default=None)
    create.add_argument("--schedule", default=None, help="ISO datetime, e.g. 2026-01-01T18:00")
    create.add_argument("--publish", action="store_true", help="publish when finished")
    create.add_argument("--no-voice", action="store_true")
    create.add_argument("--no-captions", action="store_true")
    create.add_argument("--no-music", action="store_true")

    publish = sub.add_parser("publish", help="publish an existing job")
    publish.add_argument("job_id")
    publish.add_argument("--account", default=None)

    listing = sub.add_parser("list", help="list recent jobs")
    listing.add_argument("--limit", type=int, default=20)

    sub.add_parser("providers", help="show which AI providers are active")

    serve = sub.add_parser("serve", help="run the web dashboard")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "create":
        return asyncio.run(_create(args))
    if args.command == "publish":
        return asyncio.run(_publish(args))
    if args.command == "list":
        return _list(args)
    if args.command == "providers":
        return _providers(args)
    if args.command == "serve":
        return _serve(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
