"""Screensaver photos: pictures you copy into a folder on the device, served to the screen as small resized copies.

The originals are never changed or exposed. The screen only gets a JPEG shrunk to SKYBOLT_PHOTO_MAX pixels on its longest
side, turned upright (phones store rotation in EXIF) and stripped of all metadata, location included. Copies are cached in
a folder beside the database. Picture ids come from scanning the folder, so no path from a request ever reaches the disk.
"""
import hashlib
import logging
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image, ImageOps

router = APIRouter(prefix="/api/photos", tags=["photos"])
log = logging.getLogger("skybolt.photos")

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}  # iPhone HEIC is not supported: export as JPEG
INDEX_TTL = 60  # seconds a folder scan is reused before looking again
CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}  # the id changes whenever the file does
_render_lock = threading.Lock()  # one resize at a time: the Pi is small


def photos_dir(request: Request) -> Path:
    s = request.app.state.settings
    return s.photos_dir or s.db_path.parent / "photos"


def cache_dir(request: Request) -> Path:
    return request.app.state.settings.db_path.parent / "photo_cache"


def _scan(root: Path) -> dict[str, Path]:
    """id -> file for every picture under root, in name order. Hidden files (macOS '._name.jpg' copies) are skipped."""
    found: dict[str, Path] = {}
    if not root.is_dir():
        return found
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.suffix.lower() not in EXTENSIONS or any(part.startswith(".") for part in rel.parts) or not p.is_file():
            continue
        st = p.stat()
        found[hashlib.sha1(f"{rel}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()[:20]] = p
    return found


def _index(request: Request, refresh: bool = False) -> dict[str, Path]:
    st = request.app.state
    cached = getattr(st, "photo_index", None)
    if refresh or cached is None or time.time() - cached[0] > INDEX_TTL:
        cached = (time.time(), _scan(photos_dir(request)))
        st.photo_index = cached
    return cached[1]


def _render(src: Path, dest: Path, longest: int) -> None:
    with Image.open(src) as im:
        im.draft("RGB", (longest, longest))  # JPEG: decode at a reduced size, much faster and lighter on a Pi
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((longest, longest), Image.Resampling.LANCZOS)
        tmp = dest.with_suffix(".tmp")
        im.save(tmp, "JPEG", quality=82, optimize=True, progressive=True)  # no exif= argument: metadata is dropped
    tmp.replace(dest)


@router.get("", response_model=list[str])
def list_photos(request: Request):
    """Ids of the pictures to show. Also forgets cached copies of pictures that were deleted or replaced."""
    ids = _index(request, refresh=True)
    cache = cache_dir(request)
    if cache.is_dir():
        for f in cache.glob("*.jpg"):
            if f.stem.split("-")[0] not in ids:
                f.unlink(missing_ok=True)
    return list(ids)


@router.get("/{photo_id}")
def get_photo(request: Request, photo_id: str):
    st = request.app.state
    src = _index(request).get(photo_id) or _index(request, refresh=True).get(photo_id)  # a just-copied file is not in a stale scan
    bad = getattr(st, "photo_bad", None)
    if bad is None:
        st.photo_bad = bad = set()
    if src is None or photo_id in bad:
        raise HTTPException(404, "photo not found")
    longest = request.app.state.settings.photo_max
    dest = cache_dir(request) / f"{photo_id}-{longest}.jpg"
    if not dest.exists():
        with _render_lock:
            if not dest.exists():
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    _render(src, dest, longest)
                except Exception as e:  # unreadable or truncated file: remember it so we do not retry on every request
                    log.warning("cannot use photo %s: %s", src.name, e)
                    bad.add(photo_id)
                    raise HTTPException(404, "photo not readable")
    return FileResponse(dest, media_type="image/jpeg", headers=CACHE_HEADERS)
