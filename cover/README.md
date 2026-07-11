# Cover assets

Launcher icon (APK cover) lives here.

## What's in this folder

`file.enc` — Despite the `.enc` extension, this file is actually a **JFIF / JPEG**
image (magic bytes `FF D8 FF E0 ... JFIF`, EXIF tag "Photoshop 3.0"). The bytes
are not encrypted — it was just shipped with a misleading extension.

## Before your first `buildozer android debug`

`buildozer.spec` expects a file at `cover/icon.jpg`. Run:

```bash
bash scripts/prepare_cover.sh          # idempotent, doesn't need chmod
```

Plain `cp cover/file.enc cover/icon.jpg` is the manual equivalent. The
shebang invocation goes through `bash` rather than `./scripts/...` because
git checkouts default to `core.fileMode = false` for shared checkouts —
the executable bit on `scripts/prepare_cover.sh` would NOT survive
`git pull`. A direct invocation of `./scripts/prepare_cover.sh` therefore
fails with `Permission denied` until you `chmod +x scripts/prepare_cover.sh`
by hand. If you want the shortcut form to work after pulling, run
`chmod +x scripts/prepare_cover.sh` once.

Buildozer then reads the bytes, detects the JPEG signature, and packages it
into the APK as the launcher icon at every density the device asks for.

## Prerequisite toolchain (read this first)

These instructions target **Debian / Ubuntu + WSL**. macOS users replace
`apt` with `brew install` (formula names differ — e.g. `brew install
pkg-config autoconf automake libtool python@3.11 openssl readline sqlite3
xz sdl2 sdl2_image sdl2_mixer sdl2_ttf gstreamer` — **`pkg-config` is
required** so `sdl2_image` can find its headers at p4a recipe compile
time, otherwise you get a cryptic `"jpeglib.h not found"` error);
Windows users go through Android Studio's SDK Manager GUI (no
`sdkmanager` shell flow on Windows). The Debian / Ubuntu + WSL recipe
below is the only one fully automatable here.

`buildozer android debug` is **not a one-liner** on a fresh machine. The
table below lists the ten deps needed before the very first Android build.
Missing any of them yields a confusing mid-compile error (`Android SDK not
found`, `No module named 'Cython'`, `Build-tools not installed`, etc.) rather
than a clean pre-flight check.

| Tool              | Required version                  | Install on Debian/Ubuntu                 |
| ----------------- | --------------------------------- | ---------------------------------------- |
| Python            | 3.10+                             | `sudo apt install python3 python3-venv` |
| pip + wheel       | latest                            | `sudo apt install python3-pip`           |
| Git               | 2.x                               | `sudo apt install git`                   |
| Cython            | **>=0.29.36, <3.0.0**              | `pip install 'Cython>=0.29.36,<3.0.0'` (Kivy 2.3 recipes break on Cython 3.x ABI *and* on 0.29.0 which is missing buffer-protocol support) |
| Buildozer         | 1.5.x                             | `pip install buildozer`                  |
| JDK               | 17                                | `sudo apt install openjdk-17-jdk`        |
| Android cmdline   | latest                            | download from `developer.android.com`    |
| SDK platform 34   | required                          | `sdkmanager "platforms;android-34"`      |
| Build-tools       | 34.0.0                            | `sdkmanager "build-tools;34.0.0"`        |
| Android NDK       | **r26d (26.3.11579264)**          | `sdkmanager "ndk;26.3.11579264"`         |

### Linux host build libraries (mandatory on Debian/Ubuntu)

Kivy 2.3.x + KivyMD 1.1.x compile Cython extensions against the host's
system libraries — p4a won't bring them along. Forget even one and the
recipe build aborts with a cryptic C-level error several minutes into the
first compile:

```bash
sudo apt install -y \
    libffi-dev libssl-dev libsqlite3-dev libpango1.0-dev \
    libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev \
    libgstreamer1.0-dev libasound2-dev
```

### Tell Buildozer where the SDK and JDK live

After installing the SDK components, expose their paths so Buildozer can
find them. Two equivalent ways:

**(a) Interactive shell / dev box:** put these in `~/.bashrc` so they
persist across sessions.

```bash
export ANDROIDSDK=$HOME/Android/Sdk

# If multiple JDKs are installed (or apt just added openjdk-17-jdk), point
# javac at JDK 17 *before* the JAVA_HOME expansion. `--set` is non-interactive;
# `--config` requires a TTY.
sudo update-alternatives --set javac /usr/lib/jvm/java-17-openjdk-amd64/bin/javac
sudo update-alternatives --set java  /usr/lib/jvm/java-17-openjdk-amd64/bin/java

# `command -v` (POSIX) instead of `which` — works in dash/BusyBox/Alpine
# containers where `which` may be missing entirely.
export JAVA_HOME=$(dirname $(dirname $(readlink -f $(command -v javac))))
```

**(b) Non-interactive shell / CI / `make` / Jenkins / `crontab` / Docker:**
`~/.bashrc` is NOT sourced there, so **prepend the env vars directly** to
the `buildozer` invocation. This is the recipe that actually works
when no shell ever reads your rc files:

```bash
ANDROIDSDK=$HOME/Android/Sdk \
JAVA_HOME=$(dirname $(dirname $(readlink -f $(command -v javac)))) \
    buildozer android debug
```

The macOS equivalent for the JAVA_HOME line is `/usr/libexec/java_home
-v 17`, which Apple ships from macOS 10.5+. The Debian
`update-alternatives --set` paths in the (a) block silently no-op on
macOS; on macOS use `export JAVA_HOME=$(/usr/libexec/java_home -v 17)`
instead.

`buildozer.spec` reads the SDK location via `android.sdk_path =
$ANDROIDSDK`. The bare-dollar form is Buildozer's documented env-var
substitution; an unset `ANDROIDSDK` expands to an empty string, which
Buildozer surfaces as the misleading *"Android SDK not found"* rather
than a Python-stack `KeyError`.

### Realistic time-to-first-APK

**First end-to-end success on a clean Linux / WSL box: 1–3 hours, not
25–40 min.** The `buildozer android debug` invocation itself takes ~30 min
once the toolchain resolves, but the first attempt almost always fails on
one of: NDK version mismatch, missing `ANDROIDSDK`, missing `build-tools`,
missing Cython, missing `JAVA_HOME`, or a multi-JDK ambiguity. Each
iteration adds 30 min to several hours. Budget ~5 GB on disk for `.gradle`
/ `p4a` caches.

Kivy/Buildozer recipes have been validated against NDK **r26d / r27**; the
earlier `r25c+` baseline compiles but triggers a loud version warning
you'll then have to silence anyway.

## Desktop alternative (Step 3 not yet shipped)

The same Python source will eventually run natively under Kivy once Étape 3
(`main.py` + `ui/`) is implemented in `structure.md`. **Until that lands,
the APK pipeline is the only way to run the app — running `python main.py`
today will fail** with `ModuleNotFoundError`. Until Step 3 ships, the only
valid ways to validate the code are:

- `pytest tests/` — runs every Step 1 / Step 2 module on the dev box.
- An Android emulator or device — once the APK is built.

## Swapping the launcher icon

Replace `cover/icon.jpg` with the new image (PNG or JPG) at the same path.
If you commit a true PNG (recommended once you have a transparent foreground),
no update to `buildozer.spec` is required — the path stays
`%(source.dir)s/cover/icon.jpg` regardless of format, and Buildozer deduces
the type from the file header.

## Presplash

We deliberately leave `presplash.filename` commented out in `buildozer.spec`
so the app launches without a full-screen splash that would awkwardly crop
the launcher icon. Drop a dedicated 1280×1920 portrait image at
`cover/presplash.jpg` later and uncomment the line when you do.

---

## Release Signing (Path A — GitHub Releases sideload)

Pour installer ton APK sur un téléphone et **pouvoir le mettre à jour sans réinstall**, il faut signer l'APK avec un **keystore release stable** (et non le keystore debug jetable que Buildozer génère par défaut). Sans ça, Android refuse toute mise à jour venant d'une APK signée avec une clé différente — les utilisateurs seraient bloqués à la première version installée.

### Step 1 — Génération du keystore release (UNE FOIS)

Lance le helper :

```bash
bash scripts/setup_keystore.sh
```

Il va :
- Demander un mot de passe de keystore (≥ 6 caractères, **note-le dans ton password manager**)
- Demander un mot de passe de clé
- Demander une identité DN (CN = ton nom d'éditeur, OU = département, O = organisation, L = ville, S = région, C = pays)
- Générer `transas-release.jks` à la racine du projet (validité 27 ans)
- Écrire un helper `scripts/last-keystore-info.txt` (à supprimer après avoir noté les infos dans ton password manager)

**NEVER commit le fichier `transas-release.jks`** — il est dans `.gitignore` par défaut. Si tu le commits accidentellement, régénère-le immédiatement, invalide l'ancien via ta CA, et push l'APK re-signé.

### Step 2 — Active la signature release dans `buildozer.spec`

Dans la section **Release signing** du fichier `buildozer.spec`, décommente les deux lignes :

```ini
android.keystore = %(source.dir)s/transas-release.jks
android.keyalias = transas     # ou ton alias custom
```

### Step 3 — Export des mots de passe

```bash
export P4A_RELEASE_KEYSTORE_PASSWD='...'
export P4A_RELEASE_KEY_PASSWD='...'
export P4A_RELEASE_KEYALIAS=transas     # optionnel — default matche buildozer.spec
```

Pour un build **local dev** : ces exports vont dans `~/.bashrc` (ou un `.envrc.local` *non commit*).

Pour un build **CI via GitHub Actions** : ces 4 secrets vont dans *Settings → Secrets and variables → Actions* :
- `KEYSTORE_BASE64`     ← `base64 -w 0 transas-release.jks`
- `KEYSTORE_PASSWORD`   ← `P4A_RELEASE_KEYSTORE_PASSWD`
- `KEY_ALIAS`           ← `P4A_RELEASE_KEYALIAS` (default : `transas`)
- `KEY_PASSWORD`        ← `P4A_RELEASE_KEY_PASSWD`

### Step 4 — Build + push tag (déclenche la GitHub Actions release workflow)

```bash
# Sanity check local : build avec keystore release
buildozer android debug    # maintenant signé avec transas-release.jks

# Tag → déclenche .github/workflows/release.yml → APK uploadé sur GitHub Releases
git tag v0.1
git push --tags
# → 1-3h plus tard : https://github.com/El-hadj10/TransAs/releases/latest
```

### Gotcha : `git checkout` ne préserve pas le keystore

Ton `transas-release.jks` est dans `.gitignore`, donc un `git pull` ne va jamais l'écraser (parce qu'il ne le track pas). Mais le bit exécutable de `scripts/setup_keystore.sh` et `scripts/sign_release.sh` peut être perdu sur un checkout si `core.fileMode = false` (default sur les checkouts partagés). Solutions :

1. Invoque via `bash scripts/setup_keystore.sh` (jamais `./setup_keystore.sh`) — fonctionne sans bit exécutable
2. Sinon `chmod +x scripts/setup_keystore.sh scripts/sign_release.sh scripts/prepare_cover.sh` une fois après chaque pull

### Gotcha : laptop perdu ou réinstallé

Si tu perds `transas-release.jks` ET que tu n'as pas le mot de passe dans un password manager, **tu ne peux plus signer les mises à jour**. Les utilisateurs devront désinstaller et réinstaller l'app manuellement (perte de données locales — `transas.db` dans `app.user_data_dir`). Solutions :

- Backup chiffré du keystore sur un service comme KeePass + cloud sync (Bitwarden premium, KeePassXC + cloud)
- Export chiffré GPG du keystore vers un dépôt privé séparé
- Noter l'empreinte SHA-256 du keystore (visible via `keytool -list -v`) dans un endroit séparé
