from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db as dbmod
from .config import Settings, get_settings
from . import weather as weathermod
from .chores import router as chores_router
from .photos import router as photos_router
from .events import router as events_router
from .google import Google, urllib_http
from .google_routes import finish_sign_in, router as google_router
from .gsync import Syncer
from .members import router as members_router


# The UI is local and small: make the browser revalidate it on every load so a deploy shows up at once
# (without this, Chromium guesses a freshness time and the wall display can keep running old JS/CSS).
NO_CACHE = {"Cache-Control": "no-cache"}


class FreshStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def create_app(settings: Settings | None = None, google_http=urllib_http) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = dbmod.connect(settings.db_path)
        app.state.settings = settings
        app.state.weather_cache = {}
        app.state.weather_fetch = weathermod.fetch_open_meteo
        app.state.google = Google(settings, google_http)
        app.state.syncer = Syncer(settings, app.state.google)
        app.state.oauth_pending = {}
        app.state.syncer.start()
        yield
        app.state.syncer.stop()
        app.state.db.close()

    app = FastAPI(title="Skybolt", lifespan=lifespan)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    app.include_router(events_router)
    app.include_router(members_router)
    app.include_router(chores_router)
    app.include_router(weathermod.router)
    app.include_router(google_router)
    app.include_router(photos_router)

    @app.get("/", include_in_schema=False)
    def index(request: Request, state: str = "", code: str = "", error: str = ""):
        if state:  # coming back from Google sign-in
            return finish_sign_in(request, state, code, error)
        page = Path(settings.ui_dir) / "index.html"
        if not page.exists():
            raise HTTPException(404)
        return FileResponse(page, headers=NO_CACHE)

    if Path(settings.ui_dir).exists():
        app.mount("/", FreshStaticFiles(directory=settings.ui_dir, html=True), name="ui")
    return app


def run() -> None:
    s = get_settings()
    uvicorn.run(create_app(s), host=s.host, port=s.port)


if __name__ == "__main__":
    run()
