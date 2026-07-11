#!/usr/bin/env bash
# TransAs — one-shot cover-asset preparation for Buildozer.
#
# ``buildozer.spec`` references ``%(source.dir)s/cover/icon.jpg``, but the
# only file in the cover folder right now is ``cover/file.enc`` (which is
# actually a JFIF/JPEG despite the misleading extension). Run this script
# once before the first ``buildozer android debug`` and the icon will be
# picked up automatically.
#
# Usage:
#     bash scripts/prepare_cover.sh          # Linux / macOS / WSL
#     powershell -File scripts/prepare_cover.ps1   # Windows (if we add one)
#
# NOTE: invoke through ``bash`` rather than ``./scripts/prepare_cover.sh``.
# The executable bit is not preserved by `git checkout`; a direct
# invocation will fail with `Permission denied`. If you want the
# shortcut form, run ``chmod +x scripts/prepare_cover.sh`` once.
#
# Idempotent: if the destination already exists it is left untouched.

set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${ROOT_DIR}/cover/file.enc"
DST="${ROOT_DIR}/cover/icon.jpg"

if [[ ! -f "${SRC}" ]]; then
    echo "[prepare_cover] ERROR: ${SRC} not found." >&2
    exit 1
fi

if [[ -f "${DST}" ]]; then
    echo "[prepare_cover] ${DST} already exists, leaving it as-is."
    exit 0
fi

cp "${SRC}" "${DST}"
echo "[prepare_cover] copied -> ${DST}"
