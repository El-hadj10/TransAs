#!/usr/bin/env bash
# TransAs — release APK signing helper.
#
# Use this AFTER ``buildozer android debug`` (or ``release``) has produced
# ``bin/transas-0.1-*-debug-unsigned.apk`` (or similar — depends on the
# buildozer+recipe version).
#
# Actually: Buildozer 1.5+ produces a signed-by-default APK if you point it at
# a real keystore via ``buildozer.spec`` (see ``android.keystore`` / keyalias
# fields). Use this script **only** if you want to re-sign an APK with a
# different keystore, or if ``buildozer.spec`` doesn't have keystore fields
# (rare).
#
# Reads signing parameters from environment variables (consistent with the
# GitHub Actions secrets in .github/workflows/release.yml).
#
# Invocation
# ----------
#     export KEYSTORE=/secure/path/transas-release.jks
#     export KEYSTORE_PASSWORD=...
#     export KEY_ALIAS=transas
#     export KEY_PASSWORD=...
#     bash scripts/sign_release.sh path/to/bin/transas-0.1-arm64-v8a-debug.apk
#
# Outputs
# -------
# The input APK, **aligned** and signed in-place (via apksigner). Original
# APK path is preserved — we only validate that the resulting APK is properly
# v2 / v3 signed.
#
# Notes
# -----
# - Need ``apksigner`` on PATH. On Debian/Ubuntu: ``sudo apt install
#   apksigner`` (or use ``$ANDROIDSDK/build-tools/<v>/apksigner``).
# - ``zipalign`` is also required — same package as apksigner.
#
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: bash scripts/sign_release.sh <path-to-apk>" >&2
    echo "" >&2
    echo "Env vars required:" >&2
    echo "  KEYSTORE          — absolute path to .jks file" >&2
    echo "  KEYSTORE_PASSWORD — keystore unlock password" >&2
    echo "  KEY_ALIAS         — alias inside the keystore" >&2
    echo "  KEY_PASSWORD      — key-specific password" >&2
    exit 1
fi

APK="${1}"

# Validate inputs
for v in KEYSTORE KEYSTORE_PASSWORD KEY_ALIAS KEY_PASSWORD; do
    if [[ -z "${!v:-}" ]]; then
        echo "[sign_release] missing env var: ${v}" >&2
        exit 2
    fi
done

if [[ ! -f "${KEYSTORE}" ]]; then
    echo "[sign_release] keystore file not found: ${KEYSTORE}" >&2
    exit 3
fi

if [[ ! -f "${APK}" ]]; then
    echo "[sign_release] APK not found: ${APK}" >&2
    exit 3
fi

# Locate apksigner + zipalign — prefer Android SDK if available
APKSIGNER=""
ZIPALIGN=""

if [[ -n "${ANDROIDSDK:-}" && -d "${ANDROIDSDK}/build-tools" ]]; then
    # Pick the highest build-tools version available
    BT_VERSION=$(ls -1 "${ANDROIDSDK}/build-tools" 2>/dev/null | sort -V | tail -1)
    if [[ -n "${BT_VERSION}" ]]; then
        APKSIGNER="${ANDROIDSDK}/build-tools/${BT_VERSION}/apksigner"
        ZIPALIGN="${ANDROIDSDK}/build-tools/${BT_VERSION}/zipalign"
    fi
fi

# Fallback to system paths
if [[ -z "${APKSIGNER}" ]] || ! command -v "${APKSIGNER}" >/dev/null 2>&1; then
    APKSIGNER=$(command -v apksigner || true)
fi
if [[ -z "${ZIPALIGN}" ]] || ! command -v "${ZIPALIGN}" >/dev/null 2>&1; then
    ZIPALIGN=$(command -v zipalign || true)
fi

if [[ -z "${APKSIGNER}" ]]; then
    echo "[sign_release] apksigner not found. Install it or set \$ANDROIDSDK." >&2
    echo "  Debian/Ubuntu: sudo apt install apksigner" >&2
    echo "  Or grab it from \$ANDROIDSDK/build-tools/<version>/" >&2
    exit 4
fi
if [[ -z "${ZIPALIGN}" ]]; then
    echo "[sign_release] zipalign not found. Same fix as apksigner." >&2
    exit 4
fi

echo "[sign_release] apksigner: ${APKSIGNER}"
echo "[sign_release] zipalign : ${ZIPALIGN}"
echo "[sign_release] keystore : ${KEYSTORE} (alias ${KEY_ALIAS})"
echo "[sign_release] APK      : ${APK}"

# Step 1 — zipalign (4-byte alignment), overwriting a tmp copy
TMP_ALIGNED="$(mktemp -u --suffix=.apk)"
echo "[sign_release] step 1/2 — zipalign"
"${ZIPALIGN}" -p -f 4 "${APK}" "${TMP_ALIGNED}"

# Step 2 — apksigner v2 + v3 signing
echo "[sign_release] step 2/2 — apksigner sign"
"${APKSIGNER}" sign \
    --ks "${KEYSTORE}" \
    --ks-pass "pass:${KEYSTORE_PASSWORD}" \
    --ks-key-alias "${KEY_ALIAS}" \
    --key-pass "pass:${KEY_PASSWORD}" \
    --v1-signing-enabled false \
    --v2-signing-enabled true \
    --v3-signing-enabled true \
    --out "${APK}" \
    "${TMP_ALIGNED}"

# Step 3 — verify
echo "[sign_release] verifying signature..."
"${APKSIGNER}" verify -v --print-certs "${APK}"

rm -f "${TMP_ALIGNED}"

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  ✓ Signed: ${APK}"
echo ""
echo "  Next: upload to GitHub Releases via the workflow at"
echo "        .github/workflows/release.yml — push a tag like v0.1:"
echo ""
echo "    git tag v0.1                              # → triggers release.yml"
echo "    git push --tags                           # → workflow runs"
echo "    → bin/transas-*.apk uploaded as a release asset"
echo "════════════════════════════════════════════════════════════════"
