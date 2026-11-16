# Plan de parité TransAs × Circuit — 3 fonctions prioritaires

> **Date** : 2026-10-27 · **Auteur** : NOUR (agent de El-hadj) · **Statut** : fonction 1
> implémentée et testée (27/10/2026) ; fonctions 2 et 3 cadrées, non implémentées
>
> **Règle de parité** : on reproduit le **comportement observable** (flux livreur),
> jamais le code, les actifs, la marque ou les assets de Circuit. Implémentation
> indépendante dans l'architecture TransAs (Kivy/KivyMD, SQLite, Nominatim/OSRM,
> garde-fous Adreno connus via `report_bug.md` BUG-001/BUG-010).
> **Hors périmètre assumé** : comptes/cloud sync, multi-livreur, facturation,
> tuiles cartographiques tierces, ressemblance de marque.

## État de l'art TransAs (vérifié le 27/10)

| Capacité | État |
| :--- | :--- |
| Ajout manuel / import CSV-colle (dédoublonné, 500 max) | ✅ `batch_import.parse_addresses` |
| Géocodage Nominatim + cache JSON local + rate-limit 1 req/s | ✅ `core/geocoder.py` |
| Matrice OSRM (distances) + repli Haversine | ✅ `core/router.py` |
| Optimisation hiérarchique NN + 2-opt + K-Means (>40 arrêts) | ✅ `core/optimizer.py` |
| Départ/Arrivée fixes (chemin ouvert) | ✅ `optimize_open_path` |
| Tournée du jour persistée (SQLite), statut livré/pending | ✅ `database/` |
| Navigation vers l'app du choix (`geo:` intent) | ✅ `ui/services/navigation.py` |
| Carte offline (canvas primitives, rendu PNG Pillow) | ✅ `safe_screen.RouteMap` + `folium_renderer` |
| **Position GPS courante du livreur** | ✅ `ui/services/location.py` + bouton « RÉOPTIMISER D'ICI » (27/10/2026) |
| **Preuve de livraison (photo/note/horodatage)** | ❌ `mark_delivered()` = simple UPDATE status |
| **ETA par arrêt** | ❌ `eta_text=""` codé en dur ; matrice sans durées |

---

## Fonction 1 — Réoptimisation en direct depuis ma position ⭐ priorité haute

**Comportement Circuit visé** : le livreur, en cours de tournée, appuie sur
« optimiser les arrêts restants » ; l'app part de sa position GPS actuelle et
réordonne uniquement les colis non livrés.

**Écart TransAs** : `_optimize()` n'utilise que le champ texte « Départ » ;
aucune géolocalisation (le manifeste ne déclarait que `INTERNET,
ACCESS_NETWORK_STATE`). Les colis livrés sont déjà exclus (`list_pending()`),
la moitié du besoin existait.

**Implémenté le 27/10/2026** :
1. `buildozer.spec` : `android.permissions` inclut désormais
   `ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION` (permissions runtime, jamais
demandées au démarrage).
2. `ui/services/location.py` (nouveau, sans dépendance UI) :
   - `has_permission()` / `request_permission(cb)` via `android.permissions`
     (réponse « approximative » d'Android 12+ acceptée : c'est assez précis
     pour réordonner une tournée) ;
   - `request_position(cb)` : **une** demande de fix (`requestSingleUpdate`
     GPS puis réseau, attente 12 s) sur un thread court, puis repli sur le
     cache le plus récent (`getLastKnownLocation`, 10 min max) ;
   - `_pick_fix()` pure (le plus récent, rejette le périmé/le malformé) et
     `__post` vers le thread Kivy ; toute panne Java est avalée → `None`.
3. `SafeTransAsScreen` : bouton **« RÉOPTIMISER D'ICI »** partageant sa
   rangée avec « IMPORTER (CSV) » — une troisième colonne dans la rangée
   OPTIMISER/NAVIGUER serait illisible à 360 dp, et une rangée dédiée
   mangerait 44 dp de la liste d'arrêts. Demande la permission au premier
   appui seulement, puis `ParcelInput(id=-1, address="Ma position", lat, lon)`
   en `start_point`.
4. `OptimizeController` : correction du chemin **départ seul** — le point de
   départ est un nœud de la matrice, il doit donc aussi être un nœud de
   l'optimisation ; l'ancien code le traitait comme un simple décalage
   d'indices (matrice décalée, dernier arrêt potentiellement perdu). Nouveau
   test de non-régression dans `tests/test_ui_layer.py`.
5. Repli sans GPS (desktop, permission refusée, fix introuvable) : message
   explicite dans la barre de statut et bouton ré-activé ; le champ « Départ »
   manuel reste la voie de secours (aucune adresse inventée).

**Critères d'acceptation** :
- Sur S24, 3 arrêts en attente, 1 livré : le nouvel ordre commence à la position
  réelle de l'appareil ; les livrés ne réapparaissent pas ; tournée sauvegardée.
- Permission refusée : message clair, aucun crash, bouton ré-activé en mode manuel.
- Tests : `_pick_fix` pure (le plus récent, périmé rejeté, entrées
  malformées ignorées), `_best_known_fix` avec faux LocationManager,
  dégradation hors Android, et contrôleur avec `start_point` injecté sans
  géocodage du fix (aucun réseau requis). ✅ 5 tests ajoutés, suite verte.

**Risques** : consentement de localisation One UI (délai de 12 s puis repli
sur le cache) ; batterie (one-shot, aucun abonnement continu) ;
`requestSingleUpdate` est déprécié depuis l'API 30 — toujours présent en API
34, et toute exception retombe sur le cache.

---

## Fonction 2 — Preuve de livraison (photo + note) ⭐ priorité moyenne

**Comportement Circuit visé** : à la remise du colis, le livreur attache une
photo et/ou une note ; la preuve est horodatée et consultable ensuite.

**Écart TransAs** : `DBManager.mark_delivered()` ne fait qu'écrire
`status='delivered'` — ni `delivered_at`, ni note, ni pièce jointe.

**Périmètre MVP** :
1. Migration SQLite additive et gardée (`PRAGMA table_info`) :
   `delivered_at TEXT NULL`, `note TEXT NULL`, `photo_path TEXT NULL`
   sur `parcels`.
2. Flux « LIVRÉ » enrichi : second appui (ou bouton « Preuve ») → popup
   **Preuve de livraison** en widgets Kivy simples (pas d'élévation KivyMD,
   garde-fous Adreno) : champ note + bouton « Photo ».
3. Photo : intent système `MediaStore.ACTION_IMAGE_CAPTURE` via jnius,
   **sans déclarer la permission CAMERA** (l'app système prend la photo),
   récupération du fichier dans `files/proofs/<parcel_id>.jpg`.
   Pas d'appareil photo sur desktop → bouton grisé, note fonctionnelle.
4. Historique du jour : popup texte listant les livrés avec note +
   « Ouvrir la photo » (Intent `ACTION_VIEW`) — **aucun rendu d'image in-app**
   (BUG-010 : pas de widget Image sans texture valide).

**Critères d'acceptation** :
- Livrer avec note + photo sur S24 → ligne en base avec `delivered_at`,
  fichier présent dans `files/proofs/`, app stable après rotation/retour.
- Sans caméra (desktop) : note seule, pas de crash ; base compatible
  anciennes lignes (colonnes NULL tolérées).

**Risques** : URI de la caméra système sur Samsung (copier le flux dans
notre espace immédiatement, ne jamais dépendre de l'URI externe) ; taille des
photos (recompresser en JPEG qualité 80 via Pillow au moment de la copie —
Pillow 13 est dans l'APK).

---

## Fonction 3 — ETA par arrêt ⭐ priorité moyenne

**Comportement Circuit visé** : chaque arrêt affiche une heure d'arrivée
estimée ; le résumé affiche la durée totale de tournée.

**Écart TransAs** : la matrice OSRM ne demande que
`annotations=distance` (pas de durées) ; `eta_text=""` est un stub dans
`main_screen._render_cards` et `parcel_card` a déjà le slot graphique.

**Périmètre MVP** :
1. `router.get_distance_matrix` : demander `annotations=distance,duration`
   et renvoyer `(distances, durations)` ; repli Haversine pour les durées via
   une vitesse moyenne urbaine constante (`Config.AVG_SPEED_KMH = 30`).
2. Fonction pure `core/eta.py` : `compute_etas(order, durations,
   departure_time, service_min)` → liste d'horodatages ISO ; testable sans
   réseau.
3. UI : remplir `eta_text` (`≈ 14:35`) sur chaque carte (main_screen) +
   résumé « 12 arrêts · 34 km · ~1 h 12 » (route_overview).
4. Repli offline : ETA estimés, préfixe « ~ » et badge matrice « Haversine »
   (le badge existe déjà).

**Critères d'acceptation** :
- Après optimisation, chaque carte porte une ETA croissante ; hors ligne,
  les ETA restent affichés avec « ~ ».
- Tests : ETA math (ordre, cumul, service), parsing durations OSRM, repli.

**Risques** : matrice OSRM plus lourde (durées = 2× les champs) — mesurable,
négligeable à l'échelle d'une tournée ; heure de départ figée à l'optimisation
(acceptable en MVP).

---

## Ordre d'implémentation recommandé

1. **Fonction 1** (réoptimisation GPS) — cœur du métier, écart le plus visible.
2. **Fonction 3** (ETA) — faible coût, effet « pro » immédiat, slot UI déjà prêt.
3. **Fonction 2** (preuve de livraison) — migration + caméra, à faire en dernier
   avec un test appareil dédié.

Chaque fonction : tests unitaires d'abord (`tests/`), rebuild APK, vérification
sur S24 Ultra via ADB (procédure du journal du 26/10).
