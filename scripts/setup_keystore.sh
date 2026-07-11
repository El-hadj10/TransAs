#!/usr/bin/env bash
# TransAs — release keystore setup helper.
#
# Generates ``transas-release.jks`` for stable APK signing. **You** choose the
# passwords and identity so only you control the keys.
#
# Why this matters
# ----------------
# - Buildozer's ``android debug`` subcommand signs with a throwaway keystore,
#   which means **users cannot upgrade** from one debug build to the next —
#   Android refuses to install an APK signed by a different key.
# - F-Droid (and IzzyOnDroid) require stable release signing.
# - We use this same keystore for GitHub Releases direct-install.
#
# Invocation
# ----------
#     bash scripts/setup_keystore.sh                    # interactive
#     bash scripts/setup_keystore.sh --alias transas    # custom alias
#
# Outputs
# -------
# - ``transas-release.jks``  (NEVER commit — already in .gitignore)
# - ``scripts/last-keystore-info.txt``  (private — keeps a *local* note of the
#   alias + fingerprints so you don't lose them; do NOT commit this file
#   either — move it to a password manager and delete it)
#
# After this script, you must:
# 1. Move the keystore out of the repo (or encrypt it locally).
# 2. Store the FOUR secrets (key-password, store-password, alias, base64-encoded
#    .jks) in GitHub → Settings → Secrets & variables → Actions:
#       * KEYSTORE_BASE64   — base64 of the .jks file
#         (base64 -w 0 transas-release.jks > /tmp/keystore.b64)
#       * KEYSTORE_PASSWORD — keystore unlock password (the one you'll type here)
#       * KEY_ALIAS         — alias name (default: ``transas``)
#       * KEY_PASSWORD      — key-specific password (often same as keystore)
#
set -euo pipefail

ALIAS="${1:-transas}"
KEY_ALGO="RSA"
KEY_SIZE=2048
VALIDITY_DAYS=10000  # ~27 years
KEYSTORE_NAME="transas-release.jks"
INFO_NOTE="scripts/last-keystore-info.txt"

# Idempotency — refuse to overwrite an existing keystore
if [[ -f "${KEYSTORE_NAME}" ]]; then
    echo "[setup_keystore] ${KEYSTORE_NAME} already exists." >&2
    echo "                  Refusing to overwrite. Move it elsewhere or " >&2
    echo "                  delete it first if you really want a new one." >&2
    exit 1
fi

# keytool is part of the JDK — quick pre-flight
if ! command -v keytool >/dev/null 2>&1; then
    echo "[setup_keystore] keytool not found. Install openjdk-17-jdk-headless:" >&2
    echo "                  sudo apt install openjdk-17-jdk-headless" >&2
    exit 1
fi

echo "════════════════════════════════════════════════════════════════"
echo "  TransAs — Release Keystore Setup"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "  Keytool will ask you for:"
echo "    - Keystore password      (min 6 chars — store securely!)"
echo "    - Key password           (often same; can differ)"
echo "    - Distinguished Name     (CN, OU, O, L, S, C)"
echo "    - Alias                  : ${ALIAS}"
echo "    - Validity               : ${VALIDITY_DAYS} days (~27 years)"
echo ""
echo "  Use a real identity you control — the **CN** field is what will"
echo "  appear in your APK's signing certificate."
echo ""
read -r -p "  Press Enter to launch keytool, or Ctrl-C to abort..."
echo ""

keytool -genkeypair \
    -keystore "${KEYSTORE_NAME}" \
    -alias "${ALIAS}" \
    -keyalg "${KEY_ALGO}" \
    -keysize "${KEY_SIZE}" \
    -validity "${VALIDITY_DAYS}" \
    -v

# Lock the file down — keystore is sensitive material
chmod 600 "${KEYSTORE_NAME}"

# Local note (NEVER commit) — capture SHA-256 + alias to help user keep
# track. This file is on .gitignore but adds defense-in-depth.
{
    echo "TransAs release keystore — local note (DO NOT COMMIT)"
    echo "Generated on: $(date -Iseconds)"
    echo "Alias: ${ALIAS}"
    echo "Keystore file: ${KEYSTORE_NAME}"
    echo "SHA-256 of keystore: $(sha256sum "${KEYSTORE_NAME}" | awk '{print $1}')"
    echo ""
    echo "GitHub Secrets to set (Settings → Secrets and variables → Actions):"
    echo "  - KEYSTORE_BASE64:   \$(base64 -w 0 ${KEYSTORE_NAME})"
    echo "  - KEYSTORE_PASSWORD: <keystore unlock password you typed above>"
    echo "  - KEY_ALIAS:         ${ALIAS}"
    echo "  - KEY_PASSWORD:      <key-specific password>"
} > "${INFO_NOTE}"
chmod 600 "${INFO_NOTE}"

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Keystore generated: ${KEYSTORE_NAME}"
echo "  SHA-256: $(sha256sum "${KEYSTORE_NAME}" | awk '{print $1}')"
echo ""
echo "  Next steps:"
echo "  1. Move ${KEYSTORE_NAME} to a safe location outside the repo."
echo "  2. Move ${INFO_NOTE} to a password manager, then delete it locally."
echo "  3. Set the four GitHub Secrets listed in ${INFO_NOTE}."
echo "  4. Push a tag (git tag v0.1 && git push --tags) to trigger the"
echo "     .github/workflows/release.yml workflow."
echo "════════════════════════════════════════════════════════════════"
