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
    secret_key: str = ""  # encrypts the stored Google token
    google_credentials: Path = ROOT / "credentials.json"
    timezone: str = ""  # IANA name, e.g. America/Denver (needed for repeating Google events)
    google_sync_seconds: int = 120  # 0 turns the background sync off


def local_tz_name() -> str:
    tz = os.environ.get("TZ", "").lstrip(":")
    if "/" in tz and not tz.startswith("/"):
        return tz
    parts = os.path.realpath("/etc/localtime").split("zoneinfo/", 1)
    return parts[1] if len(parts) == 2 else ""


def _path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def get_settings() -> Settings:
    _load_dotenv(ROOT / ".env")
    db = _path(os.environ.get("SKYBOLT_DB_PATH", "data/skybolt.db"))
    return Settings(
        db_path=db,
        host=os.environ.get("SKYBOLT_HOST", "127.0.0.1"),
        port=int(os.environ.get("SKYBOLT_PORT", "8000")),
        ui_dir=ROOT / "ui",
        lat=float(os.environ.get("SKYBOLT_LAT", "40.7128")),
        lon=float(os.environ.get("SKYBOLT_LON", "-74.0060")),
        location_name=os.environ.get("SKYBOLT_LOCATION_NAME", "Home"),
        units=os.environ.get("SKYBOLT_UNITS", "imperial"),
        secret_key=os.environ.get("SKYBOLT_SECRET_KEY", ""),
        google_credentials=_path(os.environ.get("SKYBOLT_GOOGLE_CREDENTIALS", "credentials.json")),
        timezone=os.environ.get("SKYBOLT_TIMEZONE") or local_tz_name(),
        google_sync_seconds=int(os.environ.get("SKYBOLT_GOOGLE_SYNC_SECONDS", "120")),
    )
