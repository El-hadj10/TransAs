# Project knowledge — TransAs

## What this project is
Mobile APK for delivery couriers in France that optimizes daily routes (>100 stops/day). Offline-first philosophy: algorithm runs locally; only geocoding/routing hit external APIs.

## Confirmed decisions
- **Region:** France (métropole) — Nominatim/OSRM coverage is excellent.
- **Daily volume:** >100 → trigger the hierarchical clustering pipeline (see Algorithm).
- **Target platform:** Android APK via Kivy/KivyMD + Buildozer.
- **Parcel status states (minimal):** `pending` → `delivered` (only 1 actionable transition in the field).

## Stack
- **Language:** Python 3.10+
- **UI:** Kivy / KivyMD (cross-platform, APK export via Buildozer) — _not in deps yet, added in Step 3_
- **Optimization:** Hierarchical clustering (K-Means) + Nearest Neighbor + 2-opt, pure Python.
- **Geocoding:** Nominatim (OpenStreetMap) with on-disk JSON cache to respect 1 req/sec limit.
- **Routing/Distance matrix:** OSRM `/table` endpoint with Haversine fallback.
- **Persistence:** SQLite (local) — _added in Step 2_.

## Algorithm (Step 1.4)
`core.optimizer.optimize(stops, distance_matrix, start=0)` returns the reordered indices. Pipeline:
1. If `len(stops) ≤ 40`: direct **Nearest Neighbor** from `start` + **2-opt** improvement.
2. Else: **K-Means** clustering with K-means++ seeding, targeting ≤30 stops/cluster and ≥3 clusters.
3. **Order clusters** by running NN + 2-opt on a centroid distance matrix, starting from the cluster that contains `start`.
4. **Optimize each cluster** independently with NN + 2-opt on the OSRM road distance sub-matrix.
5. **Rotate** the start stop to position 0 in its cluster; concatenate all clusters.
6. Assert: every input index appears exactly once and `start` is at position 0.

Why this and not OR-Tools: OR-Tools' C++ binding breaks Buildozer packaging and adds ~50 MB to the APK. For 300 stops, K-Means(10 × 30) + 2-opt gives <1 s on Android and ~2-3% over optimum — acceptable for daily logistics.

## Quickstart
- Setup: `pip install -r requirements.txt`
- Test: `pytest tests/`
- Dev: `python main.py` _(Step 3)_
- Build APK: `bash scripts/prepare_cover.sh && buildozer android debug` _(Step 4.2)_

## Project tree (canonical, per structure.md)
```
trans_as/
├── main.py, config.py, requirements.txt, conftest.py
├── core/{__init__,geocoder,router,optimizer}.py
├── database/{__init__,db_manager,models}.py   (Step 2)
├── ui/screens, ui/components/                  (Step 3)
└── tests/{__init__,test_geocoder,test_router,test_optimizer}.py
```

## Conventions
- **Strict layering:** UI never calls APIs directly — go through `core/`. `core/` never imports from `ui/` or `database/`.
- **Offline-first:** network may fail. Always have a Haversine fallback in `router.py` and a local cache in `geocoder.py`.
- **One-handed UX priority:** keep screens dense, tappable, minimal chrome.
- **Testability:** every `core/` module must be testable without a UI; every module must support `cache=`/`retries=` injection for unit tests (no network in tests).
- **Test isolation:** use `conftest.py` at project root to add root to `sys.path`; tests inject the cache dir via `tmp_path` fixture.
- **Status states:** parcels have explicit status — current spec is `pending` and `delivered` only.
- **Buildozer caveat:** keep dependencies pure-Python where possible (no C++ bindings).
- **Git `core.fileMode`:** git checkouts default to `core.fileMode = false` for shared checkouts, so the executable bit on `scripts/prepare_cover.sh` is **not** preserved across `git pull`. Invoke the script through `bash scripts/...` (not `./scripts/...`), or `chmod +x scripts/prepare_cover.sh` once after every pull.

## Gotchas / things to avoid
- **Nominatim rate limits:** 1 req/sec strict. Always read cache first; use a `User-Agent` identifying the app (ToS violation otherwise).
- **OSRM public demo server:** flaky and rate-limited; `router.py` must retry and fall back to Haversine.
- **TSP on mobile:** classical exact TSP is O(n!). Stick to NN + 2-opt or the hierarchical pipeline — never pull in OR-Tools or scipy optimizers (Android packaging risk).
- **Buildozer on Termux:** requires manual `python-for-android` setup — don't assume `buildozer` is on PATH.
- **K-Means degenerate clusters:** `kmeans_cluster` must skip empty clusters and avoid `ZeroDivisionError` on empty groups.
- **No CI yet:** tests are run manually by the coding agent after each roadmap step.
- **Android `db_path` default:** `Path(config.Config.PROJECT_ROOT) / "transas.db"` may resolve to a non-writable bundled-assets directory on p4a. Step 3 must pass `app.user_data_dir` to `DBManager(db_path=...)`; do not ship with the dev default.
- **APK cover asset:** `cover/file.enc` is a real JPEG (magic `FF D8 FF E0 ... JFIF`), just badly named. `buildozer.spec` references **`cover/icon.jpg`** — the file lives next to `file.enc`, **not at the project root**. Use `bash scripts/prepare_cover.sh` (idempotent, doesn't need chmod+x) before the first `buildozer android debug`, or copy manually. Swap-to-PNG keeps the same path + filename; Buildozer deduces the format from the header. `presplash.filename` is currently left commented (drop a 1280×1920 portrait splash at `cover/presplash.jpg` to enable it).
- **APK build prerequisites:** first `buildozer android debug` is **not a one-line** on a fresh machine. Needs Python 3.10+, pip + wheel, git, **`Cython >=0.29.36, <3.0.0`** (NOT just `<3.0.0`: pip's resolver can pick the very old 0.29.0 which is missing buffer-protocol support and breaks Kivy 2.3 — the explicit floor `>=0.29.36` matches the Cython Kivy 2.3 ships its wheels against. Modern Cython 3.x has ABI breaks that crash the recipe 20 min into gradle); Buildozer 1.5.x; **JDK 17** (with `sudo update-alternatives --set javac /usr/lib/jvm/java-17-openjdk-amd64/bin/javac` and `--set java` when multiple JDKs are installed — use the non-interactive `--set` form in CI / Docker / Termux, the `--config` form prompts and hangs); Android cmdline-tools, SDK platform 34, build-tools 34.0.0; **NDK r26d (26.3.11579264)** (r25c triggers a loud version warning; newer p4a wants r26d/r27); plus **`apt install`** ~10 host libs for the SDL2 family (`libffi-dev libssl-dev libsqlite3-dev libpango1.0-dev libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev libgstreamer1.0-dev libasound2-dev`). Don't forget to **`export ANDROIDSDK=$HOME/Android/Sdk`** plus **`export JAVA_HOME=...`** before invoking buildozer — for **non-interactive** shells (CI / `make` / `crontab` / Jenkins / Docker), **`~/.bashrc` is NOT sourced**, so prepend env vars directly to the buildozer command (the canonical form is in § "Build / APK canonical commands" below). On macOS, `JAVA_HOME=$(/usr/libexec/java_home -v 17)` replaces the Debian `update-alternatives` chain. `buildozer.spec` reads the SDK via `android.sdk_path = $ANDROIDSDK` (Buildozer's documented bare-dollar env-var substitution; an unset `ANDROIDSDK` expands to empty, surfaced as the misleading *"Android SDK not found"* rather than a Python `KeyError`). **Realistic first end-to-end success: 1–3 hours on a clean Linux/WSL box, ~5 GB on disk** — the first attempt almost always fails on one tool (NDK, build-tools, Cython, JAVA_HOME, multi-JDK clash) and iterating costs another 30 min each. Full toolchain + apt list + macOS (`brew install pkg-config autoconf automake libtool python@3.11 openssl readline sqlite3 xz sdl2 sdl2_image sdl2_mixer sdl2_ttf gstreamer`) / Windows (Android Studio GUI) variants — see `cover/README.md` § Prerequisite toolchain.
- **Desktop debug without APK:** **`python main.py` does not work today** — `main.py` is part of Étape 3 and has not been written yet. Use `pytest tests/` to validate Python modules on the dev box; the APK pipeline is the only end-to-end runtime until Étape 3 ships.
- **Cover asset `presplash`:** `buildozer.spec` lines related to `presplash.filename` are intentionally commented out — a launcher icon squashed into a full-screen splash looks wrong. Drop a 1280×1920 portrait image at `cover/presplash.jpg` and uncomment the line when you do.

## Roadmap status
- ✅ Step 0: `knowledge.md` filled (this file)
- ✅ Step 1: Foundations + algorithmic core (geocoder, router, optimizer)
  - `core/geocoder.py` — Nominatim + JSON cache + threading.Lock rate limiter.
  - `core/router.py` — OSRM `/table` with retries, Haversine fallback.
  - `core/optimizer.py` — K-Means + NN + 2-opt hierarchical pipeline.
  - **29 tests passing** (`pytest tests/`) in ~0.26 s (Step 1 only).
- 🚧 Step 2: SQLite persistence (`database/db_manager.py`, `database/models.py`)
  - `database/models.py` — `Parcel`, `Tour` dataclasses (timezone-aware created_at).
  - `database/db_manager.py` — `_SCHEMA: tuple` class-level DDL + per-statement `conn.execute(...)` inside `BEGIN IMMEDIATE`/`COMMIT` (atomic init even on Python legacy autocommit). CRUD complet + validation `list[int]` sur `ordered_indices`.
  - **17 tests covering schema, indexes by name, CRUD parcels, tour round-trip, corrupt-indices ValueError, non-list payload ValueError**.
- ⏳ Step 3: Kivy/KivyMD UI (screens importable on PC; APK build deferred)
- ⏳ Step 4: Integration tests + `buildozer.spec`

## Carry-over from Step 1 reviews (deferred to Step 3)
- `core.router.get_distance_matrix` returns a plain matrix; for the UI layer we'll wrap it in a small `MatrixSource` enum (`OSRM | HAVERSINE`) and broadcast a Kivy event when falling back, so the driver can see a "OSRM unreachable" toast.
- `optimizer.optimize()` raises `RuntimeError` on invariant breaks; the UI must catch it and surface a friendly "Itinéraire impossible".
- OSRM URL length: Step 3 caller must call `router.get_distance_matrix` per‑cluster (≤30 coords), assemble locally; the cluster structure is already exposed by the optimizer.

## Build / APK canonical commands (run from project root)

```bash
# ───── 0. One-off on a fresh Debian/Ubuntu box ─────────────────────────
sudo apt install -y \
    libffi-dev libssl-dev libsqlite3-dev libpango1.0-dev \
    libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev \
    libgstreamer1.0-dev libasound2-dev
sudo apt install openjdk-17-jdk
sudo update-alternatives --set javac /usr/lib/jvm/java-17-openjdk-amd64/bin/javac
sudo update-alternatives --set java  /usr/lib/jvm/java-17-openjdk-amd64/bin/java
pip install 'Cython>=0.29.36,<3.0.0' buildozer
# Android cmdline tools + sdkmanager step is documented in cover/README.md §
# Prerequisite toolchain (SDK platform 34, build-tools 34.0.0, NDK r26d).

# ───── 1. Prepare the cover asset (idempotent) ───────────────────────
bash scripts/prepare_cover.sh

# ───── 2a. Export SDK + JDK for interactive shells (add to ~/.bashrc) ─
export ANDROIDSDK=$HOME/Android/Sdk
export JAVA_HOME=$(dirname $(dirname $(readlink -f $(command -v javac))))
# macOS equivalent (Apple-shipped):
#    export JAVA_HOME=$(/usr/libexec/java_home -v 17)

# ───── 2b. Non-interactive shells (CI / Docker / make / crontab):
#        prepend env vars directly on the same line:
ANDROIDSDK=$HOME/Android/Sdk \
JAVA_HOME=$(dirname $(dirname $(readlink -f $(command -v javac)))) \
    buildozer android debug

# ───── 3. Build the APK ──────────────────────────────────────────────
# First run: 1–3 hours. Subsequent runs: ~5 min.
buildozer android debug
```

The APK lands in `bin/transas-0.1-<arch>-debug.apk`
(`armeabi-v7a` / `arm64-v8a` / `x86_64` depending on `android.arch`).
Install on a device with `adb install bin/transas-*.apk`.
