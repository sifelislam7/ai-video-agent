"""FastAPI entrypoint for the AI Video Agent."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .agent.scheduler import get_scheduler
from .config import OUTPUT_DIR, get_settings
from .routers import jobs, system, tiktok
from .storage import get_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ai-video-agent")

WEB_DIR = Path(__file__).parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    get_store()  # create the database eagerly
    scheduler = get_scheduler()
    scheduler.start()
    log.info(
        "AI Video Agent %s ready — TikTok mode: %s",
        __version__, "live" if settings.live_tiktok else "mock",
    )
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(
    title="AI Video Agent",
    description=(
        "وكيل ذكاء اصطناعي لإنشاء فيديوهات وصور قصيرة ونشرها على تيك توك.\n\n"
        "AI agent that writes, renders and publishes short-form content to TikTok."
    ),
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(tiktok.router)
app.include_router(system.router)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
# Generated media must be publicly reachable for TikTok's PULL_FROM_URL mode.
app.mount("/media", StaticFiles(directory=str(OUTPUT_DIR)), name="media")
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/", include_in_schema=False, response_model=None)
async def dashboard():
    index = WEB_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"name": "AI Video Agent", "docs": "/docs"})


@app.get("/favicon.ico", include_in_schema=False, response_model=None)
async def favicon():
    icon = WEB_DIR / "favicon.svg"
    if icon.exists():
        return FileResponse(icon, media_type="image/svg+xml")
    return JSONResponse({}, status_code=404)


def main() -> None:  # pragma: no cover - console entrypoint
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    main()
