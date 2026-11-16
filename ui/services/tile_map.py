"""Stitched OpenStreetMap raster basemap for the route canvas.

Why this module exists: ``RouteMap`` used to paint a bare grid because the
public OSM tile endpoints answered 403 — the requests went out without an
identifying ``User-Agent``, which the tile usage policy rejects.  With a
proper UA and a disk cache the same endpoints serve real street tiles, so
the canvas can finally show roads and place names under the route.

Cost model (deliberate):

  * one render only covers the on-screen canvas, i.e. ~12 to ~20 tiles at
    ``Config.TILE_SCALE``; they are fetched through a small thread pool;
  * every tile is cached under ``${CACHE_DIR}/tiles/{z}/{x}/{y}.png``, so a
    second render of the same area performs **no** network I/O at all;
  * the result is a single PNG: one texture, one ``Rectangle`` on the Kivy
    side, which keeps the GPU work minimal on the Adreno target (cf.
    BUG-010 — many image instructions used to trip the VBO compiler).

Pillow is imported *inside* the functions, never at module import: BUG-001
showed that loading Pillow's native bindings during bootstrap can SIGSEGV
the SDL thread.  Importing this module is therefore cheap and safe; the
first Pillow load happens when a basemap is actually requested.
"""
from __future__ import annotations

import io
import logging
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

import requests

import config

_logger = logging.getLogger("transas.ui.tile_map")

Coord = Tuple[float, float]  # (lat, lon)

# Source tiles are always 256 px; ``Config.TILE_SCALE`` stretches them.
TILE_SIZE = 256
# Web Mercator is clamped here, the usual convention for slippy maps.
_MAX_LAT = 85.05112878


@dataclass
class MapRender:
    """A rendered basemap plus the projection that produced it.

    ``project`` returns *fractions* of the canvas (0..1, origin top-left) so
    the Kivy widget can lay the route out over the texture at any size — it
    survives a widget resize instead of drifting off the streets.
    """

    png: bytes
    zoom: int
    width: int
    height: int
    tiles_total: int
    tiles_fetched: int
    origin_x: float
    origin_y: float
    scale: float

    def project(self, lat: float, lon: float) -> Tuple[float, float]:
        px, py = _world_px(lat, lon, self.zoom, self.scale)
        return (
            (px - self.origin_x) / max(self.width, 1),
            (py - self.origin_y) / max(self.height, 1),
        )

    def unproject(self, fx: float, fy: float) -> Coord:
        """Inverse of :meth:`project` — canvas fraction to ``(lat, lon)``.

        Used by the pan/zoom gestures: after the user drags the map by
        ``(dx, dy)`` the point that ended up in the middle of the widget is
        the new centre of the next render.
        """
        world = TILE_SIZE * (2 ** self.zoom) * self.scale
        x = self.origin_x + fx * self.width
        y = self.origin_y + fy * self.height
        lon = x / max(world, 1.0) * 360.0 - 180.0
        n = math.pi - 2.0 * math.pi * y / max(world, 1.0)
        lat = math.degrees(math.atan(math.sinh(n)))
        return max(min(lat, _MAX_LAT), -_MAX_LAT), lon


# ---------------------------------------------------------------------------
# Web Mercator helpers
# ---------------------------------------------------------------------------

def _world_px(lat: float, lon: float, zoom: int, scale: float = 1.0) -> Tuple[float, float]:
    """Project ``(lat, lon)`` to pixels in the whole world at ``zoom``."""
    world = TILE_SIZE * (2 ** zoom)
    clamped = max(min(lat, _MAX_LAT), -_MAX_LAT)
    lat_rad = math.radians(clamped)
    x = (lon + 180.0) / 360.0 * world
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * world
    return x * scale, y * scale


def _tile_of(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    """Return the integer ``(x, y)`` tile holding ``(lat, lon)``."""
    x, y = _world_px(lat, lon, zoom)
    limit = 2 ** zoom - 1
    return (
        min(max(int(x // TILE_SIZE), 0), limit),
        min(max(int(y // TILE_SIZE), 0), limit),
    )


def fit_zoom(
    coords: Sequence[Coord],
    width: int,
    height: int,
    *,
    scale: float = 1.0,
    max_zoom: int = 17,
    pad_ratio: float = 0.15,
) -> int:
    """Highest zoom whose bounding box still fits inside the canvas.

    ``pad_ratio`` keeps the outermost stops away from the borders so their
    numbered markers are never clipped by the canvas edge.
    """
    if not coords:
        return config.Config.TILE_DEFAULT_ZOOM
    pad = min(width, height) * pad_ratio
    usable_w = max(width - 2 * pad, 1.0)
    usable_h = max(height - 2 * pad, 1.0)

    for zoom in range(max_zoom, 1, -1):
        pts = [_world_px(lat, lon, zoom, scale) for lat, lon in coords]
        span_x = max(p[0] for p in pts) - min(p[0] for p in pts)
        span_y = max(p[1] for p in pts) - min(p[1] for p in pts)
        # A single point (or a pile of identical ones) fits at any zoom: stop
        # at the default so the first render is a readable neighbourhood, not
        # a 3-metre square of asphalt.
        if span_x < 1.0 and span_y < 1.0:
            return min(config.Config.TILE_DEFAULT_ZOOM, max_zoom)
        if span_x <= usable_w and span_y <= usable_h:
            return zoom
    return 2


# ---------------------------------------------------------------------------
# Tile acquisition (network + disk cache)
# ---------------------------------------------------------------------------

def tile_cache_dir() -> Path:
    """Directory holding cached tiles (created on demand)."""
    return Path(config.Config.CACHE_DIR) / config.Config.TILE_CACHE_SUBDIR


def _tile_path(zoom: int, x: int, y: int) -> Path:
    return tile_cache_dir() / str(zoom) / str(x) / f"{y}.png"


def _open_tile(data: bytes):
    """Decode raw PNG bytes to an RGB image (Pillow imported lazily)."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        return img.convert("RGB")


def _get_tile(
    zoom: int, x: int, y: int,
) -> Optional[Tuple[object, bool]]:
    """Return ``(image, from_cache)`` for one tile, or ``None`` on failure.

    The disk copy wins over the network: the basemap for a given area is
    static enough, and re-downloading it on every refresh would hammer a
    service that is explicitly rate-limited.
    """
    path = _tile_path(zoom, x, y)
    if path.exists():
        try:
            return _open_tile(path.read_bytes()), True
        except Exception:
            _logger.warning("tile cache entry unreadable, refetching: %s", path)
            try:
                path.unlink()
            except OSError:
                pass

    url = config.Config.TILE_URL.format(z=zoom, x=x, y=y)
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": config.Config.TILE_USER_AGENT,
                "Accept": "image/png,image/*;q=0.8",
            },
            timeout=(
                config.Config.TILE_CONNECT_TIMEOUT_SEC,
                config.Config.TILE_TIMEOUT_SEC,
            ),
        )
        response.raise_for_status()
        payload = response.content
        image = _open_tile(payload)
    except Exception as exc:  # noqa: BLE001 — offline/403/timeouts are normal
        _logger.info("tile %s/%s/%s unavailable: %s", zoom, x, y, exc)
        return None

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(payload)
        tmp.replace(path)
    except OSError as exc:
        _logger.info("tile cache write failed (%s): %s", path, exc)
    return image, False


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _load_font(size: int):
    """Best available font, falling back to Pillow's built-in one."""
    from PIL import ImageFont

    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except (OSError, IOError):
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def fold_gesture(
    render: MapRender,
    dx: float = 0.0,
    dy: float = 0.0,
    live_scale: float = 1.0,
    *,
    max_zoom: Optional[int] = None,
) -> Tuple[int, float, float]:
    """Turn a finished pan/zoom gesture into the next viewport.

    ``dx``/``dy`` are the pixels the map was dragged by (right/up positive)
    and ``live_scale`` the visual scale applied during the pinch. The result
    is ``(zoom, lat, lon)`` for a fresh render — pure maths, so the widget
    can be tested without a GL context.
    """
    limit = int(max_zoom if max_zoom is not None else config.Config.TILE_MAX_ZOOM)
    steps = math.log2(live_scale) if live_scale and live_scale > 0 else 0.0
    zoom = int(round(render.zoom + steps))
    zoom = max(config.Config.TILE_MIN_ZOOM, min(zoom, limit))
    lat, lon = render.unproject(
        0.5 - dx / max(render.width, 1),
        0.5 + dy / max(render.height, 1),
    )
    return zoom, lat, lon


def render_map(
    coords: Sequence[Coord],
    width: int,
    height: int,
    *,
    zoom: Optional[int] = None,
    scale: Optional[float] = None,
    center: Optional[Coord] = None,
) -> Optional[MapRender]:
    """Stitch the basemap covering ``coords`` into one PNG.

    ``center``/``zoom`` pin the viewport explicitly (pan and zoom gestures);
    without them the viewport is auto-fitted to the tour's bounding box.

    Returns ``None`` when *no* tile could be obtained (offline, 403, broken
    cache) so the caller can keep its offline fallback instead of showing a
    white rectangle.
    """
    if not coords:
        return None

    from PIL import Image, ImageDraw

    cfg = config.Config
    width = max(64, min(int(width), 2048))
    height = max(64, min(int(height), 2048))
    scale = float(scale if scale is not None else cfg.TILE_SCALE)
    zoom = int(zoom if zoom is not None else fit_zoom(
        coords, width, height, scale=scale, max_zoom=cfg.TILE_MAX_ZOOM,
    ))
    tile_px = max(int(round(TILE_SIZE * scale)), 1)

    # Canvas window around the requested centre (default: the tour's centre).
    if center is not None:
        center_x, center_y = _world_px(center[0], center[1], zoom, scale)
    else:
        pts = [_world_px(lat, lon, zoom, scale) for lat, lon in coords]
        center_x = (max(p[0] for p in pts) + min(p[0] for p in pts)) / 2.0
        center_y = (max(p[1] for p in pts) + min(p[1] for p in pts)) / 2.0
    origin_x = center_x - width / 2.0
    origin_y = center_y - height / 2.0

    limit = 2 ** zoom
    first_x = int(math.floor(origin_x / tile_px))
    last_x = int(math.floor((origin_x + width - 1) / tile_px))
    first_y = int(math.floor(origin_y / tile_px))
    last_y = int(math.floor((origin_y + height - 1) / tile_px))
    wanted = [
        (tx, ty)
        for ty in range(first_y, last_y + 1)
        for tx in range(first_x, last_x + 1)
        if 0 <= tx < limit and 0 <= ty < limit
    ]
    if not wanted:
        return None

    canvas = Image.new("RGB", (width, height), (233, 238, 242))
    draw = ImageDraw.Draw(canvas)
    fetched = 0
    placed = 0
    lock = threading.Lock()

    def work(tx: int, ty: int):
        return tx, ty, _get_tile(zoom, tx, ty)

    with ThreadPoolExecutor(max_workers=max(1, cfg.TILE_WORKERS)) as pool:
        for tx, ty, result in pool.map(lambda t: work(*t), wanted):
            if result is None:
                continue
            tile, from_cache = result
            if not from_cache:
                with lock:
                    fetched += 1
            if tile.size != (tile_px, tile_px):
                tile = tile.resize((tile_px, tile_px), Image.Resampling.LANCZOS)
            canvas.paste(
                tile,
                (
                    int(round(tx * tile_px - origin_x)),
                    int(round(ty * tile_px - origin_y)),
                ),
            )
            placed += 1

    if placed == 0:
        _logger.info("no tile available for %s stops at zoom %s", len(coords), zoom)
        return None

    # Attribution is required by the tile usage policy (ODbL).
    font = _load_font(max(int(round(11 * scale)), 11))
    label = "© OpenStreetMap"
    text_w = draw.textlength(label, font=font)
    descent = max(int(round(14 * scale)), 14)
    draw.rectangle(
        [width - text_w - 8, height - descent - 3, width, height],
        fill=(255, 255, 255),
    )
    draw.text(
        (width - text_w - 4, height - descent), label,
        fill=(90, 90, 90), font=font,
    )

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return MapRender(
        png=buffer.getvalue(),
        zoom=zoom,
        width=width,
        height=height,
        tiles_total=len(wanted),
        tiles_fetched=fetched,
        origin_x=origin_x,
        origin_y=origin_y,
        scale=scale,
    )


def clear_cache() -> None:
    """Delete every cached tile (ops/debug helper)."""
    root = tile_cache_dir()
    for path in sorted(root.rglob("*.png")):
        try:
            path.unlink()
        except OSError:
            pass
    for path in sorted(root.rglob("*.tmp")):
        try:
            path.unlink()
        except OSError:
            pass
    _logger.info("tile cache cleared: %s", root)
