"""Global configuration for TransAs.

All runtime tunables live here so the rest of the codebase stays declarative.
Centralised config also makes unit-test injection straightforward (patch
attributes on `config.Config`).
"""
from pathlib import Path


class Config:
    # --- Project paths ----------------------------------------------------
    PROJECT_ROOT: str = str(Path(__file__).resolve().parent)

    # --- Nominatim (OpenStreetMap geocoding) -------------------------------
    NOMINATIM_URL: str = "https://nominatim.openstreetmap.org"
    # Nominatim ToS requires an identifying User-Agent; otherwise requests get 403.
    NOMINATIM_USER_AGENT: str = "TransAs/1.0 (delivery optimizer)"
    NOMINATIM_TIMEOUT_SEC: int = 15
    # 1.1 s = small margin above the 1 req/sec limit; the geocoder rate-limits
    # via a module-level timer based on this.
    NOMINATIM_MIN_DELAY_SEC: float = 1.1

    # --- OSRM (distance / duration matrix) --------------------------------
    OSRM_URL: str = "https://router.project-osrm.org"
    OSRM_TIMEOUT_SEC: int = 30
    OSRM_MAX_RETRIES: int = 3

    # --- OSM raster tiles (map background) --------------------------------
    # The tile service answers 403 to requests without an identifying
    # User-Agent, which is why the map background was removed in the first
    # place. Keep this string descriptive and stable.
    TILE_URL: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    TILE_USER_AGENT: str = "TransAs/1.0 (delivery route planner; personal use)"
    TILE_TIMEOUT_SEC: float = 12.0
    TILE_CONNECT_TIMEOUT_SEC: float = 3.05
    # Source tiles are 256 px. They are drawn at 512 px because Kivy renders
    # this UI far larger than a browser would at the same density; at 1:1 the
    # street names baked into the tiles are unreadable (see tile_map.py).
    TILE_SCALE: float = 2.0
    TILE_MAX_ZOOM: int = 17
    # Never zoom out past a continent: the tour would be a single dot.
    TILE_MIN_ZOOM: int = 2
    # Zoom used when the tour has a single point (or none, i.e. Paris centre).
    TILE_DEFAULT_ZOOM: int = 14
    TILE_WORKERS: int = 4

    # --- Local caches ------------------------------------------------------
    CACHE_DIR: str = str(Path(PROJECT_ROOT) / ".cache")
    GEOCODING_CACHE_FILE: str = "geocoding_cache.json"
    TILE_CACHE_SUBDIR: str = "tiles"

    # --- TSP / clustering defaults ----------------------------------------
    # Hierarchical pipeline kicks in above this size.
    OPTIMIZER_SMALL_LIMIT: int = 40
    # Maximum stops per cluster in the hierarchical mode.
    OPTIMIZER_MAX_STOPS_PER_CLUSTER: int = 30
    # Minimum number of clusters regardless of input size, to avoid trivial splits.
    OPTIMIZER_MIN_CLUSTERS: int = 3

    # --- Parcel status states (MVP: minimal) -------------------------------
    STATUS_PENDING: str = "pending"
    STATUS_DELIVERED: str = "delivered"
