import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader (avoids a dependency). Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


@dataclass(frozen=True)
class Settings:
    db_path: Path
    host: str
    port: int
    ui_dir: Path
    lat: float = 40.7128
    lon: float = -74.0060
    location_name: str = "Home"
    units: str = "imperial"  # or metric


def get_settings() -> Settings:
    _load_dotenv(ROOT / ".env")
    db = Path(os.environ.get("SKYBOLT_DB_PATH", "data/skybolt.db"))
    if not db.is_absolute():
        db = ROOT / db
    return Settings(
        db_path=db,
        host=os.environ.get("SKYBOLT_HOST", "127.0.0.1"),
        port=int(os.environ.get("SKYBOLT_PORT", "8000")),
        ui_dir=ROOT / "ui",
        lat=float(os.environ.get("SKYBOLT_LAT", "40.7128")),
        lon=float(os.environ.get("SKYBOLT_LON", "-74.0060")),
        location_name=os.environ.get("SKYBOLT_LOCATION_NAME", "Home"),
        units=os.environ.get("SKYBOLT_UNITS", "imperial"),
    )
