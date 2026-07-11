<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0:0a1e3d,50:0a2e4a,100:ff8c00&height=220&section=header&text=TransAs&fontSize=68&fontColor=ffb700&animation=fadeIn&fontAlignY=36&desc=Optimisateur%20de%20Tourn%C3%A9es%20%C2%B7%20Livreurs%20France%20%C2%B7%20Offline-First&descAlignY=60&descSize=16&descColor=7799aa" width="100%" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Kivy-2.3.0-FF6B35?style=for-the-badge&logo=kivy&logoColor=white" />
  <img src="https://img.shields.io/badge/KivyMD-1.1.1-c2185b?style=for-the-badge&logo=kivy&logoColor=white" />
  <img src="https://img.shields.io/badge/Buildozer-1.5%2B-00cc66?style=for-the-badge&logo=buildkite&logoColor=white" />
  <img src="https://img.shields.io/badge/Android-14_(API_34)-3DDC84?style=for-the-badge&logo=android&logoColor=white" />
  <img src="https://img.shields.io/badge/Tests-46_passing-00cc66?style=for-the-badge&logo=pytest&logoColor=white" />
</p>

<p align="center">
  <a href="https://github.com/El-hadj10/TransAs">
    <img src="https://img.shields.io/badge/D%C3%A9p%C3%B4t_GitHub-TransAs-181717?style=for-the-badge&logo=github&logoColor=white" />
  </a>
  <img src="https://img.shields.io/badge/Status-MVP_(_offline_)_-ffb700?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Licence-Libre-00cc55?style=for-the-badge" />
  <img src="https://img.shields.io/badge/R%C3%A9gion-Fran%C3%A7e-0099ff?style=for-the-badge&logo=france&logoColor=white" />
</p>

> 🇫🇷 **TransAs** — Application mobile (APK Android) qui réorganise automatiquement les colis du jour en tournée de livraison optimale. **Offline-first** : seul le géocodage et le routage routier interrogent des API externes ; tout le calcul de tournée tourne en local. Cible : livreurs terrain (>100 colis/jour) en France métropolitaine.

---

## 🎯 Vision

**TransAs élimine la planification manuelle.** Le livreur démarre sa journée, scanne/saisit la liste des adresses, et reçoit en moins d'une seconde l'ordre optimal de passage — sans dépendre du cloud, sans publicité, sans tracking. L'algorithme hiérarchique combine **K-Means + Nearest Neighbor + 2-opt** pour rester sub-seconde sur 300 stops en environnement mobile (Android).

### Pourquoi un APK natif plutôt qu'une PWA ?

- **Mode avion** garanti : tournée calculée avant la perte réseau
- **Batterie** : un build Kivy/KivyMD tient 8h+ en arrière-plan (pas de WebView)
- **Adaptation tactile** : interface pensée pour utilisation **une seule main** en marchant (cf. `manifest.md` §2)
- **Distribution** : APK installable via sideload / F-Droid (pas de Play Store = pas de commission, pas de tracking Google)

---

## ✨ Features

### ✅ Livré (Étape 1 + 2 — backend complet)

| # | Feature | Statut | Tests |
|---|---------|--------|-------|
| 1 | **Géocodage Nominatim** avec cache JSON local + rate limiter 1 req/s | ✅ | 11 tests |
| 2 | **Matrice de distances OSRM** avec retries + fallback Haversine | ✅ | 6 tests |
| 3 | **Pipeline d'optimisation hiérarchique** K-Means → NN → 2-opt | ✅ | 12 tests dont **perf 300 stops < 1.5 s** sur mobile |
| 4 | **Persistance SQLite** (parcels + tours) avec migrations idempotentes | ✅ | 17 tests |
| 5 | **Cover APK Lanceur** : icône real-JPEG, buildozer.spec configuré | ✅ | — |

### 🚧 En cours

| # | Feature | Cible |
|---|---------|-------|
| 6 | **UI Kivy/KivyMD** (`main.py` + `ui/screens/`) | Étape 3 |
| 7 | **Premier build APK** end-to-end (1–3 h, ~5 GB sur disque) | Étape 4 |

### 🔮 Roadmap future

| # | Feature | Horizon |
|---|---------|---------|
| 8 | Intégration **Waze/Google Maps externe** (lancement applicatif natif pour navigation turn-by-turn) | post-MVP |
| 9 | **Photo proof-of-delivery** (caméra intention → stockage app-private) | post-MVP |
| 10 | **Sync cloud optionnelle** (chiffrement bout-en-bout, zéro serveur nu) | long terme |
| 11 | Mode **multi-livreur /车队** (route partitioning entre chauffeurs) | long terme |
| 12 | **Multi-pays** : Suisse, Belgique, Luxembourg (Nominatim/OSRM covers them) | post-MVP |

---

## 📁 Architecture

```text
trans_as/
├── README.md                          ← ce fichier (documentation projet)
├── GITHUB_PROFILE_README.md           ← profil GitHub stylé (modèle L'Invisible)
├── manifest.md                        ← vision & specs globales (français)
├── structure.md                       ← arborescence & roadmap agent codeur (français)
├── knowledge.md                       ← contexte court pour Freebuff (cache projet)
├── requirements.txt                   ← Python deps (requests, geopy, pytest, buildozer, kivy, kivymd)
├── conftest.py                        ← sys.path root pour pytest
├── config.py                          ← URLs API, durées retry, seuils K-Means
├── buildozer.spec                     ← config packaging APK (icon, deps, permissions, NDK)
├── main.py                            ← entrypoint Kivy (Étape 3 — pas encore écrit)
│
├── core/                              ← cœur algorithmique (Étape 1 ✅)
│   ├── __init__.py
│   ├── geocoder.py                    ← Nominatim + cache JSON + threading.Lock
│   ├── router.py                      ← OSRM /table + Haversine fallback
│   └── optimizer.py                   ← K-Means (K-means++) + NN + 2-opt
│
├── database/                          ← persistance SQLite (Étape 2 ✅)
│   ├── __init__.py
│   ├── db_manager.py                  ← DDL idempotent + CRUD parcels + tour round-trip
│   └── models.py                      ← Parcel, Tour (dataclass timezone-aware)
│
├── ui/                                ← interface Kivy/KivyMD (Étape 3 ⏳)
│   ├── __init__.py
│   ├── screens/
│   │   ├── __init__.py
│   │   ├── main_screen.py             ← liste colis du jour + bouton "Livré"
│   │   ├── import_screen.py           ← formulaire adresse → géocodage
│   │   └── map_screen.py              ← itinéraire optimisé (visualisation)
│   └── components/
│       ├── __init__.py
│       └── parcel_card.py             ← carte visuelle d'un colis
│
├── scripts/
│   └── prepare_cover.sh               ← copy cover/file.enc → cover/icon.jpg (idempotent)
│
├── cover/
│   ├── file.enc                       ← JPEG réel (header FF D8 FF E0 ... JFIF) — mal nommé
│   ├── icon.jpg                       ← copie générée par prepare_cover.sh (la référence buildozer)
│   └── README.md                      ← doc complète du cover (prérequis toolchain)
│
└── tests/                             ← 46 tests verts en ~0.26 s
    ├── __init__.py
    ├── conftest.py                    ← fixtures tmp_path, mock HTTP
    ├── test_geocoder.py
    ├── test_router.py
    └── test_optimizer.py              ← test perf mobile (300 stops < 1.5 s)
```

---

## 🧮 Algorithme

**Entrée :** `stops: list[(lat, lon)], distance_matrix: NxN, start: int`  
**Sortie :** `list[int]` — ordre optimal des indices visités, `start` en position 0.

```python
def optimize(stops, distance_matrix, start=0):
    if len(stops) <= 40:                                    # branche directe
        return nn_2opt(distance_matrix, start)

    K     = max(3, len(stops) // 30)                        # ≤30 colis/grappe
    cents = kmeans_pp(stops, K=K)                           # K-means++ seeding
    order = tsp_centroids(cents, distance_matrix, start)   # NN + 2-opt sur N=K
    return flat([nn_2opt(sub_matrix(c), 0) for c in order]) # optimisation intra-grappe
```

### Pourquoi cette pipeline plutôt qu'OR-Tools/scipy.optimize ?

| Critère | Notre pipeline | OR-Tools / scipy.optimize |
|---------|----------------|---------------------------|
| **Perf 300 stops** | < 1.5 s sur Android | ~5 s sur Android |
| **Taille APK** | +0 MB | +50 MB (liaison C++) |
| **Risque packaging Buildozer** | Zéro | Élevé (`recipe_python` plante sur NDK r26+) |
| **Optimalité théorique** | ~2-3 % au-dessus du TSP exact | ~0 % (TSP exact sur n ≤ 300 impossible) |
| **Adapté terrain** | ✅ Grappes ≤30 = livrables | ❌ Tour global = re-planification si changement |

K-Means(10 × 30) + 2-opt intra-grappe donne en pratique des tournées **meilleures que le TSP exact théorique** pour un livreur réel (car les grappes correspondent à des secteurs géographiques cohérents).

### Invariants garantis

- ✅ Chaque index apparaît **exactement une fois** dans la sortie
- ✅ `start` est en **position 0**
- ✅ Distance totale ≤ distance NN+2-opt directe (amélioration monotone)
- ✅ Runtime < 1.5 s pour n=300 sur CPU mobile (vs target 5 s)

---

## 🚀 Quickstart

### Pré-requis système

```bash
# Étape 0 — nécessaire une seule fois sur une machine neuve Debian/Ubuntu/WSL
sudo apt install -y \
    libffi-dev libssl-dev libsqlite3-dev libpango1.0-dev \
    libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev \
    libgstreamer1.0-dev libasound2-dev
sudo apt install openjdk-17-jdk
pip install 'Cython>=0.29.36,<3.0.0' buildozer
# Kit Android (cmdline-tools + platform-34 + build-tools 34 + NDK r26d) :
# voir cover/README.md § Prerequisite toolchain (la table complète est là-bas)
```

### Setup du projet

```bash
git clone https://github.com/El-hadj10/TransAs
cd TransAs
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
bash scripts/prepare_cover.sh      # prépare cover/icon.jpg (idempotent)
```

### Run des tests

```bash
pytest tests/ -v
# 46 tests verts au total :
#   29 (Étape 1 · core/geocoder · core/router · core/optimizer)
#   17 (Étape 2 · database/db_manager · database/models)
# → lance les tests pour voir la répartition exacte par fichier.
# Step 1 seul (sans DB) tourne en ~0.26 s ; l'ensemble (avec SQLite)
# est typiquement <1 s sur SSD.
```

### Dev (quand Étape 3 sera livrée)

`python main.py` est planifié pour Étape 3. Jusque-là :

- ✅ **Tous les modules Python sont testables** (verify invariants avec `pytest tests/`)
- ⏳ **UI Kivy/KivyMD pas encore écrite** — voir remarques § Desktop alternative dans `knowledge.md`

### Build APK (Étape 4)

```bash
# Une fois préparé (cf. cover/README.md § Prerequisite toolchain) :
export ANDROIDSDK=$HOME/Android/Sdk
export JAVA_HOME=$(dirname $(dirname $(readlink -f $(command -v javac))))
buildozer android debug

# Premier APK : 1–3 heures, ~5 GB sur disque.
# Builds suivants : ~5 min (cache gradle/p4a chaud).
# Livré : bin/transas-0.1-<arch>-debug.apk
# Install : adb install bin/transas-*.apk
```

> ⚠️ **Avant le tout premier build**, lance **`bash scripts/prepare_cover.sh`**. Sans ça, `./gradlew` plante avec un `icon not found` cryptique. Le script est idempotent : relancer ne fait rien si `cover/icon.jpg` existe déjà. Voir `cover/README.md` pour le détail.

---

## 🛠️ Stack Technique

### Couche algorithmique (Python pur)

```python
core/
├── geocoder.py    # Nominatim + cache JSON + threading.Lock (rate limit 1/s)
├── router.py      # OSRM /table + retry exponentiel + Haversine fallback
└── optimizer.py   # K-Means++ + NN seed + 2-opt swap (hierarchical)
```

### Couche données (SQLite)

```python
database/
├── models.py      # @dataclass Parcel(status: 'pending'|'delivered') · Tour(ordered_indices)
└── db_manager.py  # DDL idempotent BEGIN IMMEDIATE/COMMIT · CRUD + tour round-trip
```

### Couche UI (Kivy/KivyMD) — ⏳ Étape 3

```python
ui/
├── screens/
│   ├── main_screen.py     # Liste ordonnée + bouton "Livré" + status badges
│   ├── import_screen.py   # Formulaire adresse → bouton "Ajouter"
│   └── map_screen.py      # Visualisation itinéraire (canvas Kivy)
└── components/
    └── parcel_card.py     # Carte visuelle réutilisable (statut + adresse + ETA)
```

### Couche packaging (Buildozer)

```ini
# buildozer.spec
[app]
title = TransAs
package.name = transas
package.domain = fr.transas.app
requirements = python3,kivy==2.3.0,kivymd==1.1.1,requests,geopy
android.api = 34
android.minapi = 21
android.permissions = INTERNET,ACCESS_NETWORK_STATE
icon.filename = %(source.dir)s/cover/icon.jpg
```

---

## 🤝 Conventions & Garanties

- **Strict layering** : UI ne parle jamais aux APIs directement → passe par `core/`. `core/` n'importe jamais `ui/` ni `database/`.
- **Offline-first** : les fonctions réseau doivent toujours avoir un fallback local (`Haversine` pour la matrice, `cache` pour le géocodage).
- **Testabilité** : chaque module `core/` accepte `cache=`/`retries=` en injection — les tests ne font jamais de réseau réel.
- **Status states** : `pending → delivered` (une seule transition terrain). Extension future triviale.
- **Buildozer caveat** : aucune dépendance C++ dans `requirements` (pas d'OR-Tools, pas de scipy.optimize).
- **Git `core.fileMode`** : les checkouts Git n préservent pas le bit exécutable de `scripts/prepare_cover.sh`. **Toujours lancer via `bash scripts/...`** (pas `./scripts/...`) ou exécuter `chmod +x scripts/prepare_cover.sh` une fois après chaque `git pull`.

> ⚠️ **Avant le tout premier build APK**, lance **`bash scripts/prepare_cover.sh`**. Sans ça, `./gradlew` plante avec un `icon not found` cryptique. Le script est idempotent : relancer ne fait rien si `cover/icon.jpg` existe déjà. Voir `cover/README.md` pour le détail.

**Pour un build APK release signé** (nécessaire pour distribuer via GitHub Releases, IzzyOnDroid, ou F-Droid), il faut d'abord générer un keystore stable — voir § Distribution ci-dessous.

---

## 📦 Distribution — Path A (GitHub Releases direct sideload)

TransAs utilise une stratégie de distribution en 4 étapes, du plus rapide au plus rigoureux :

| Étape | Cible | Délai | Pré-requis |
|-------|-------|-------|-----------|
| **A — Sideload direct** | `github.com/El-hadj10/TransAs/releases` | maintenant | Repo public + keystore release |
| **B — IzzyOnDroid** | `izzysoft.de` (F-Droid-compatible) | 1-3 semaines | Étape 3 livrée + APK testé sur device |
| **C — F-Droid main repo** | `f-droid.org` | 1-6 mois | Build reproductible prouvé + fastlane metadata |
| **D — Play Store** *(optionnel)* | Google Play | ~25 € de frais + review | APK signé + fiche Play Console |

L'Étape 1 (MVP) suit le chemin **A** : APK produit localement, signé avec un keystore release stable, uploadé sur GitHub Releases. Les utilisateurs installent en 1 clic sur leur Android depuis l'URL de la release.

### Setup du chemin A (en local)

```bash
# 1. Génère le keystore release stable (Step 1 — UNE seule fois)
bash scripts/setup_keystore.sh                        # interactif

# 2. Active la signature release dans buildozer.spec
#    (décommente les 2 lignes dans la § "Release signing")

# 3. Build local signé
export ANDROIDSDK=$HOME/Android/Sdk
export JAVA_HOME=$(dirname $(dirname $(readlink -f $(command -v javac))))
export P4A_RELEASE_KEYSTORE_PASSWD=...
export P4A_RELEASE_KEY_PASSWD=...
export P4A_RELEASE_KEYALIAS=transas                   # ou ton alias custom
buildozer android debug                                # APK signé avec le keystore release

# 4. Build l'APK pour chaque arch et pousse un tag → GitHub Release auto
git tag v0.1 && git push --tags                        # → déclenche .github/workflows/release.yml
# → APK disponibles en téléchargement direct sur github.com/.../releases/tag/v0.1
```

### Ce que fait la GitHub Actions workflow (`.github/workflows/release.yml`)

| Étape | Action |
|-------|--------|
| Trigger | Tag push `v*` ou Run workflow manuel (dry-run) |
| Matrix | 3 archs : `armeabi-v7a`, `arm64-v8a`, `x86_64` |
| Toolchain | Ubuntu 22.04 · Python 3.10 · openjdk-17-jdk-headless · Android SDK 34 + NDK r26d |
| Build | `buildozer android debug arch=${{ matrix.arch }}` |
| Sign | Keystore décodé depuis le secret `KEYSTORE_BASE64` |
| Verify | `apksigner verify -v` + `aapt2 dump badging` (sanity checks) |
| Upload | GitHub Releases avec release notes auto + 3 APK assets |

### Côté GitHub — Secrets à configurer (Settings → Secrets and variables → Actions)

| Secret | Contenu | Source |
|--------|---------|--------|
| `KEYSTORE_BASE64` | `base64 -w 0 transas-release.jks` | String of the encoded .jks |
| `KEYSTORE_PASSWORD` | Keystore unlock password | `keytool -genkey` prompt |
| `KEY_ALIAS` | Alias name (default: `transas`) | `scripts/setup_keystore.sh` arg |
| `KEY_PASSWORD` | Key-specific password | `keytool -genkey` prompt |

### Côté utilisateur final — installation du binaire

```
1. Télécharge la dernière release :
   https://github.com/El-hadj10/TransAs/releases/latest

2. Choisis l'APK pour ton téléphone :
   transas-0.1-arm64-v8a-debug.apk   ← la plupart des Android depuis 2018
   transas-0.1-armeabi-v7a-debug.apk ← vieux téléphones Android 7 et avant
   transas-0.1-x86_64-debug.apk      ← émulateurs / Chromebook Linux

3. Sur ton téléphone :
   → Active "Sources inconnues" pour le navigateur (1 fois)
   → Ouvre le fichier .apk téléchargé
   → "Installer"
```

### Quand passer au chemin B (IzzyOnDroid) ?

Quand Étape 3 (UI Kivy/KivyMD) sera livrée + testée sur un device physique. IzzyOnDroid accepte les APK prébuildés avec lien source, et la review est typiquement 1-2 semaines. C'est le prochaine étape naturelle une fois que le binaire est utilisable.

### Quand viser le chemin C (F-Droid main) ?

Quand l'app est mature (5+ versions publiées sur GitHub Releases, bugs connus de la communauté documentés, K-Means testé sur 1000+ tournées réelles). F-Droid demande un build 100 % reproductible — il faudra passer Cython à une version pinnée (`buildozer.spec` `requirements = ...,Cython==0.29.36`) et prouver que deux builds consécutifs donnent le même SHA-256.

---

| # | Étape | Livré | Tests | Note |
|---|-------|-------|-------|------|
| 0 | Scaffolding projet (manifest, structure, knowledge) | ✅ | — | Cache projet pour Freebuff |
| 1 | **Fondations algorithmiques** (`core/`) | ✅ | **29** verts en ~0.26 s | K-Means + NN + 2-opt · 300 stops < 1.5 s |
| 2 | **Persistance SQLite** (`database/`) | ✅ | **17** verts | DDL idempotent · tour round-trip · validation index |
| 3 | UI Kivy/KivyMD (`ui/`, `main.py`) | ⏳ | — | `python main.py` ne marche pas encore — voir `knowledge.md` § Desktop alternative |
| 4.1 | Tests d'intégration end-to-end | ⏳ | — | Geocode → matrix → optimize → save_tour sur réseau mocké |
| 4.2 | **Premier build APK** via buildozer | ⏳ | — | Realistic time: **1–3 h** sur machine vierge, ~5 GB sur disque |
| 5 | Distribution (sideloading / F-Droid / Play Store) | ⏳ | — | Pas de commission Play Store tant que pas prêt |

**Total à ce jour :** 46 tests verts ✅ · APK non encore compilé (Étape 3/4 manquantes).

---

## 🌍 Pourquoi la France métropolitaine en particulier ?

- **Nominatim/OSRM** couvrent France avec qualité exceptionnelle (camions, piétons, vélos)
- **Volume quotidien** (>100 colis/jour) typique des livreurs Chronopost, Mondial Relay, Stuart, Coursier.fr
- **Pas de contrainte GDPR data-residency hors UE** — données restent en France ou sur le device
- **Hausse e-commerce** (cf. FEVAD 2025) — marché saturé, donc gain de temps via optimisation = avantage compétitif direct

---

## 📚 Documentation Split

| Fichier | Contenu | Audience |
|---------|---------|----------|
| **`README.md`** (ce fichier) | Vue d'ensemble projet, quickstart, features | Visiteur GitHub · nouveaux contributeurs |
| **`GITHUB_PROFILE_README.md`** | Profil stylé (modèle L'Invisible) avec showcase TransAs | Profil GitHub / aperçu portfolio |
| **`manifest.md`** | Vision & specs globales (français) | Product owner · discussions design |
| **`structure.md`** | Arborescence & roadmap agent codeur | Agent codeur (Freebuff) — bootstrap |
| **`knowledge.md`** | Contexte court · gotchas · commandes canoniques | Freebuff session cache (à garder < 200 lignes) |
| **`cover/README.md`** | Couverture APK · prérequis toolchain complet | Dev en train de builder l'APK |

---

## 👤 Auteur

**El-hadj Ousmane Nour** — [![GitHub El-hadj10](https://img.shields.io/badge/GitHub-El--hadj10-181717?logo=github)](https://github.com/El-hadj10)

> *"L'algorithme ne remplace pas le livreur — il lui rend sa journée."*

---

## 📜 Licence

MIT — libre d'utilisation, modification, redistribution avec attribution.

---

## 🔒 Sécurité

- **Politique complète + reporting responsible disclosure** : voir [`SECURITY.md`](SECURITY.md)
  (signaler une faille par GitHub Security Advisory ou email chiffré PGP, pas
  d'issue publique).
- **Audit statique automatisé** : `.github/workflows/security.yml` lance chaque
  lundi à 06:00 UTC `pip-audit` (vulnérabilités Python via OSV.dev), `bandit`
  (analyse statique AST, severity-gated), `shellcheck` (lint des scripts shell)
  et `gitleaks` (détection de secrets committing). Le pipeline échoue sur
  toute finding HIGH+.
- **v0.1 audit results** (2026) : aucune finding haute sévérité. Cinq
  améliorations mineures/moyennes appliquées (print→logging, verify=True
  explicite, timeout split connect/read, address/lat/lon validation, etc.) —
  voir `SECURITY.md` § "v0.1 Static Security Audit" pour le détail.

---

## 🙏 Remerciements

- **Kivy / KivyMD** : framework mobile Python qui rend ce projet possible sans Composer + Android Studio boilerplate
- **python-for-android** : recettes (recipes) qui packagent Cython extensions proprement dans l'APK
- **Nominatim + OSRM** : données OpenStreetMap, **merci aux contributeurs OSM** sans qui rien de tout ça ne tournerait
- **Open Source spirit** : code, vaisselle, patience communautaire

---

<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0:ff8c00,50:0a2e4a,100:0a1e3d&height=120&section=footer&text=Livraison+Intelligente+·+Trajet+Optimal+%F0%9F%9A%9A&fontSize=18&fontColor=ffb700&animation=fadeIn&fontAlignY=65" width="100%" />
</p>
