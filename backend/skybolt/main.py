from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import db as dbmod
from .config import Settings, get_settings
from . import weather as weathermod
from .chores import router as chores_router
from .events import router as events_router
from .members import router as members_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = dbmod.connect(settings.db_path)
        app.state.settings = settings
        app.state.weather_cache = {}
        app.state.weather_fetch = weathermod.fetch_open_meteo
        yield
        app.state.db.close()

    app = FastAPI(title="Skybolt", lifespan=lifespan)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    app.include_router(events_router)
    app.include_router(members_router)
    app.include_router(chores_router)
    app.include_router(weathermod.router)
    if Path(settings.ui_dir).exists():
        app.mount("/", StaticFiles(directory=settings.ui_dir, html=True), name="ui")
    return app


def run() -> None:
    s = get_settings()
    uvicorn.run(create_app(s), host=s.host, port=s.port)


if __name__ == "__main__":
    run()
