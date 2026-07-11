"""Offline route map renderer (Pillow, no tile dependency).

Public API:
    * :func:`render_route_png`  — write a PNG to ``Path`` and return it.
    * :func:`render_route_bytes` — return raw PNG bytes (Kivy Image BytesIO).
    * :func:`build_image`       — return a :class:`PIL.Image.Image` (testing).

Why Pillow instead of folium: folium ships jinja2 + an HTML/JS stack
which is un-buildable in p4a. We want a single static PNG that the APK
can hand to a Kivy ``Image`` widget without ever needing the internet.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

Coord = Tuple[float, float]  # (lat, lon)


def _bounding_box(coords: Sequence[Coord]) -> Tuple[float, float, float, float]:
    if not coords:
        return (0.0, 0.0, 0.0, 0.0)
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    pad_lat = max(0.005, (max(lats) - min(lats)) * 0.10)
    pad_lon = max(0.005, (max(lons) - min(lons)) * 0.10)
    return (
        min(lats) - pad_lat,
        max(lats) + pad_lat,
        min(lons) - pad_lon,
        max(lons) + pad_lon,
    )


def _project(
    coords: Sequence[Coord], width: int, height: int, margin: int = 48,
) -> List[Tuple[float, float]]:
    """Equirectangular projection with symmetric (X *and* Y) centring.

    Previous versions only centred vertically when the bounding box
    was wider than tall, leaving extreme aspect ratios off-centre. We
    now apply the same symmetric translation on the binding axis:
    every projected point is offset by the leftover margin so that the
    bounding box sits exactly in the centre of the canvas rectangle.
    Costs two extra additions; visible improvement on long thin routes.
    """
    min_lat, max_lat, min_lon, max_lon = _bounding_box(coords)
    span_lat = max(max_lat - min_lat, 1e-9)
    span_lon = max(max_lon - min_lon, 1e-9)
    usable_w = max(width - 2 * margin, 1)
    usable_h = max(height - 2 * margin, 1)

    # Uniform scale keeps aspect ratio honest.
    scale_x = usable_w / span_lon
    scale_y = usable_h / span_lat
    scale = min(scale_x, scale_y)

    x_leftover = usable_w - scale * span_lon
    y_leftover = usable_h - scale * span_lat
    x_offset = margin + x_leftover / 2
    y_offset = margin + y_leftover / 2
    # North-positive latitude maps downwards on screen — invert.
    pts = [
        (
            x_offset + (lon - min_lon) * scale,
            y_offset + (max_lat - lat) * scale,
        )
        for lat, lon in coords
    ]
    return pts


def _load_font(size: int) -> ImageFont.ImageFont:
    """DejaVuSans-Bold with graceful fallback chain."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial Bold.ttf",  # macOS dev fallback
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _new_canvas(
    width: int, height: int, bg: Tuple[int, int, int, int],
) -> Tuple[Image.Image, ImageDraw.ImageDraw]:
    """Allocate a fresh RGBA canvas."""
    image = Image.new("RGBA", (width, height), bg)
    return image, ImageDraw.Draw(image)


def _draw_markers(
    draw: ImageDraw.ImageDraw,
    pts: Sequence[Tuple[float, float]],
    ordered_indices: Sequence[int],
    marker_color: Tuple[int, int, int],
) -> None:
    font_big = _load_font(36)
    font_small = _load_font(22)
    start_idx = ordered_indices[0]
    for order, idx in enumerate(ordered_indices, start=1):
        x, y = pts[idx]
        if idx == start_idx:
            r = 26
            draw.ellipse((x - r, y - r, x + r, y + r), fill=marker_color)
            label = str(order)
            tw = draw.textlength(label, font=font_big)
            draw.text((x - tw / 2, y - 18), label, fill=(255, 255, 255), font=font_big)
        else:
            r = 20
            draw.ellipse(
                (x - r, y - r, x + r, y + r),
                outline=marker_color, width=4, fill=(255, 255, 255),
            )
            label = str(order)
            tw = draw.textlength(label, font=font_small)
            draw.text((x - tw / 2, y - 12), label, fill=marker_color, font=font_small)


def build_image(
    coords: Sequence[Coord],
    ordered_indices: Sequence[int],
    *,
    width: int = 720,
    height: int = 1280,
    marker_color: Tuple[int, int, int] = (10, 46, 74),
    line_color: Tuple[int, int, int] = (255, 140, 0),
    bg_color: Tuple[int, int, int, int] = (255, 255, 255, 255),
) -> Image.Image:
    """Build the PIL Image for a tour. Used by both PNG and Bytes paths."""
    image, draw = _new_canvas(width, height, bg_color)
    if not coords or not ordered_indices:
        # No data — graceful empty-state message in the middle of canvas.
        font = _load_font(28)
        msg = "Aucun itinéraire"
        tw = draw.textlength(msg, font=font)
        draw.text(
            ((width - tw) / 2, height / 2 - 14), msg,
            fill=(120, 120, 120), font=font,
        )
        return image

    pts = _project(coords, width, height)
    route_pts = [pts[i] for i in ordered_indices]
    if len(route_pts) >= 2:
        draw.line(route_pts, fill=line_color, width=4, joint="curve")
    _draw_markers(draw, pts, ordered_indices, marker_color)

    # North arrow — top-left corner, decorative only.
    font_small = _load_font(22)
    draw.text((18, 18), "↑ N", fill=(120, 120, 120), font=font_small)
    return image


def render_route_png(
    coords: Sequence[Coord],
    ordered_indices: Sequence[int],
    *,
    output_path: str | Path,
    width: int = 720,
    height: int = 1280,
    marker_color: Tuple[int, int, int] = (10, 46, 74),
    line_color: Tuple[int, int, int] = (255, 140, 0),
    bg_color: Tuple[int, int, int, int] = (255, 255, 255, 255),
) -> Path:
    """Render the tour to a PNG file at ``output_path``."""
    image = build_image(
        coords, ordered_indices,
        width=width, height=height,
        marker_color=marker_color, line_color=line_color, bg_color=bg_color,
    )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, format="PNG")
    return out


def render_route_bytes(
    coords: Sequence[Coord],
    ordered_indices: Sequence[int],
    **kwargs,
) -> bytes:
    """Render the tour and return raw PNG bytes (handy for Kivy BytesIO)."""
    image = build_image(coords, ordered_indices, **kwargs)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
