# Structure Architecturale du Projet : TransAs

Ce document définit l'arborescence du projet et distribue les composants que l'agent codeur devra implémenter de manière séquentielle[cite: 1].

## 1. Arborescence du Projet

```text
trans_as/
├── manifest.md               # Vision globale et spécifications du projet
├── structure.md              # Ce document (architecture et road-map)
├── knowledge.md              # Contexte court pour Freebuff (cache projet)
├── requirements.txt          # Dépendances Python (requests, geopy, pytest)
├── conftest.py               # Ajoute la racine au sys.path pour les tests
├── main.py                   # Point d'entrée de l'application mobile (Step 3)
├── config.py                 # Configuration globale (URLs API, caches, seuils)
├── core/                     # Cœur algorithmique et logique métier (Step 1)
│   ├── __init__.py
│   ├── geocoder.py           # Adresse -> GPS via Nominatim (avec cache JSON)
│   ├── router.py             # Matrice de distances via API OSRM (+ fallback Haversine)
│   └── optimizer.py          # Clustering K-Means + NN + 2-opt (hiérarchique)
├── database/                 # Persistance et modèles de données (Step 2)
│   ├── __init__.py
│   ├── db_manager.py         # Gestion de la base SQLite locale
│   └── models.py             # Modèles de données (Colis, Tournée)
├── ui/                       # Interface graphique (Kivy / KivyMD) (Step 3)
│   ├── __init__.py
│   ├── screens/              # Écrans de l'application
│   │   ├── __init__.py
│   │   ├── main_screen.py    # Écran principal (Liste des colis du jour)
│   │   ├── import_screen.py  # Écran d'ajout/saisie des adresses
│   │   └── map_screen.py     # Vue de l'itinéraire optimisé
│   └── components/           # Composants graphiques réutilisables
│       ├── __init__.py
│       └── parcel_card.py    # Carte visuelle d'un colis
└── tests/                    # Tests unitaires pour validation automatique
    ├── __init__.py
    ├── test_geocoder.py
    ├── test_router.py
    └── test_optimizer.py     # Inclut un test de perf (300 stops < 1.5 s)
```

## 2. Feuille de Route pour l'Agent Codeur (Tasks Roadmap)

Chaque sous-étape doit être validée (tests verts) avant de passer à la suivante.

> **Statut en cours :** ✅ Étape 1 terminée (29 tests verts, ~0.26 s). 🚧 Étape 2 en cours.

### Étape 1 : Fondations et Cœur Algorithmique (Backend Local)
* **Tâche 1.1 :** Créer `requirements.txt`, `config.py`, `conftest.py`, et tous les `__init__.py` de la structure[cite: 1].
* **Tâche 1.2 :** Implémenter `core/geocoder.py` utilisant Nominatim (avec cache local JSON pour respecter la limite de 1 req/sec) + `tests/test_geocoder.py` (mock réseau via `monkeypatch`/`tmp_path`).
* **Tâche 1.3 :** Implémenter `core/router.py` pour récupérer les matrices de distances réelles par la route via OSRM (avec retries + fallback Haversine) + `tests/test_router.py`.
* **Tâche 1.4 :** Implémenter `core/optimizer.py` — pipeline hiérarchique :
  1. Pour `n ≤ 40` : Nearest Neighbor direct + 2-opt ([cite: 1] conservé).
  2. Pour `n > 40` : **K-Means spatial** (K-means++ seeding, K ≈ ⌈n/30⌉, K ≥ 3) → **TSP inter-cluster** (NN + 2-opt sur les centroïdes) → **NN + 2-opt intra-cluster** sur la sous-matrice OSRM → **rotation** du point de départ en première position → **fusion**.
  3. Tests : `test_optimize_single_stop`, `test_optimize_empty`, `test_optimize_small_nn_plus_twoopt`, `test_two_opt_improves_over_nn`, `test_kmeans_returns_each_index_once`, **`test_optimize_under_one_second_for_300_stops`** (perf mobile), `test_optimize_start_is_first`.

### Étape 2 : Gestion des Données et Persistance
* **Tâche 2.1 :** Concevoir `database/db_manager.py` avec création des tables `parcels` (colonnes : `id INTEGER PK`, `address TEXT`, `lat REAL`, `lon REAL`, `status TEXT DEFAULT 'pending'`, `created_at TEXT`) et `tours` (id, date, ordered_indices JSON). ✅ _livré_.
* **Tâche 2.2 :** Fonctions CRUD : `add_parcel`, `update_parcel_coords`, `get_parcel`, `list_pending`, `list_all`, `mark_delivered`, `delete_parcel`, `save_tour`, `load_today_tour`, `load_tour_for_date`. ✅ _livré_.
* **Tâche 2.3 :** Tests d'intégration (`tests/test_database.py`) — schéma init, CRUD parcels, tours round‑trip, idempotence de `mark_delivered`, isolation par `tmp_path`. ✅ _livré_.

### Étape 3 : Interface Utilisateur Mobile (UI Kivy)
* **Tâche 3.1 :** `main.py` avec `ScreenManager` (main / import / map) ; ajout du package `kivy` et `kivymd` dans `requirements.txt`.
* **Tâche 3.2 :** `ui/screens/import_screen.py` (formulaire adresse → bouton "Ajouter" → géocodage).
* **Tâche 3.3 :** `ui/screens/main_screen.py` (liste ordonnée des colis + bouton "Livré" + bouton "Lancer Waze/Google Maps externe" sur la première étape).

### Étape 4 : Tests d'Intégration et Compilation APK
* **Tâche 4.1 :** Compléter `tests/` avec un test d'intégration end-to-end (geocode → matrix → optimize → save_tour).
* **Tâche 4.2 :** Préparer le fichier `buildozer.spec` requis pour la compilation finale en APK.
  - ✅ `buildozer.spec` livré à la racine (cf. `cover/README.md` pour la mise en place de l'icône).
  - 🚧 **Avant la première compilation**, exécuter `cp cover/file.enc cover/icon.jpg` (le fichier sous extension `.enc` est en réalité un JPEG valide).

## 3. Notes Architecturales Mises à Jour

* **Cover APK :** `cover/file.enc` est un **JPEG valide** (header JFIF + EXIF "Photoshop 3.0") malgré son extension trompeuse — `buildozer.spec` référence `%(source.dir)s/cover/icon.jpg` (le fichier reste **dans `cover/`**, pas à la racine). Avant le premier build : `bash scripts/prepare_cover.sh` (idempotent) pour copier l'asset. PNG avec foreground transparent préférable pour les adaptive icons Android 8+ — `buildozer.spec` est compatible sans modification, le format est inféré du contenu du fichier. `presplash.filename` reste commenté tant qu'un splash dédié 1280×1920 n'est pas ajouté à `cover/presplash.jpg`.
* **Buildozer versioning :** `package.domain = fr.transas.app` (évite la collision avec un namespace `org.transas` générique), `android.api = 34` (cible Play Store actuelle), deps pinners (`kivy==2.3.0`, `kivymd==1.1.1`) pour stabiliser la recette p4a.

* **Pipeline optimiseur (Step 1.4 révisé) :** la stratégie NN + 2-opt pure n'est viable que pour `n ≤ 40` (cf. recommendation du thinker agent). Au-delà, le clustering hiérarchique garantit < 1.5 s sur Android pour `n ≤ 300` sans dépendance native.
* **Imports :** `config.py` est importé en absolu (`import config`) — racine ajoutée à `sys.path` par `conftest.py` pour les tests, et implicitement par Kivy en production.
* **Pas d'OR-Tools / pas de scipy.optimize :** incompatibles avec le packaging Buildozer (liaison C++).
* **Statuts colis :** le scope MVP est limité à `pending` + `delivered` (livraison terrain une fois = livré, une fois = échec non différencié). Extension future triviale.
* **OSRM URL length :** l'endpoint `/table` accepte ~5–8 KB d'URL selon le déploiement. Pour 300 colis (~300 × 8 chars = 2.4 KB) c'est viable côté endpoint public, mais pour la prod `main.py` (Step 3) **doit appeler `router.get_distance_matrix` par cluster** (≤30 coords/cluster) et assembler les sous-matrices dans la matrice NxN complète, plutôt que d'envoyer un seul hit pour les 300 coords. Cette contrainte sera intégrée à l'Étape 3.
* **Concurrence UI Kivy :** `core.geocoder.geocode` est protégé par `threading.Lock`. Pas nécessaire en mono-thread UI aujourd'hui, mais ne coûte rien et protège contre de futurs appels depuis un worker thread (ex: pré-chargement du cache).
* **Invariants de l'optimiseur :** `optimize()` lève `RuntimeError` (pas `assert`) si le résultat ne couvre pas tous les indices ou si `start` n'est pas en position 0 — les invariants survivent donc à `python -O`.
