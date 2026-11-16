# Recette Android — `SafeTransAsScreen`

> **Objet** : installer et tester sur téléphone l'APK debug produit le 2026-11-16
> (nouvel écran Kivy `SafeTransAsScreen`, fond de carte OSM, géolocalisation,
> dictée, import CSV, navigation, partage/impression).
>
> **APK de référence** : `bin/transas-0.1-arm64-v8a-debug.apk`
> — 29 739 093 octets, md5 `a5698e3651be15fe38d0e96e440c2382`,
> build incrémental (NDK 28.0.13004108, Python 3.11.11, Pillow 13.0.0),
> dictée et départ temps réel vérifiés sur S24 le 2026-11-16.
>
> **Package** : `fr.transas.app.transas` — **activité** :
> `org.kivy.android.PythonActivity` (vérifié par `aapt dump badging`).
>
> Voir `install.md` §3 pour la théorie `adb`/`unauthorized`, et
> `report_bug.md` BUG-001 / BUG-010 avant de conclure à une régression native.

---

## 0. Critères d'acceptation (à lire avant de commencer)

La recette est **réussie** si, dans cet ordre :

1. l'app démarre et reste vivante **≥ 2 minutes** sans `FATAL`/`SIGSEGV` ;
2. `pidof` renvoie **le même PID** après 10 s et après 2 min (pas de boucle de mort) ;
3. les tests **T1 → T12** passent (T13 → T16 sont informatif/robustesse) ;
4. aucune régression sur les données : un arrêt marqué `LIVRÉ` le reste après
   `force-stop` + relance.

Un échec au point 1 ou 2 = régression native. **Ne pas** tenter de monkey-patch :
capture le logcat (§6), c'est la seule entrée exploitable (cf. BUG-010).

---

## 1. Pré-requis et état de l'appareil

| # | Élément | État attendu |
|---|---------|--------------|
| 1 | Téléphone en `arm64-v8a`, Android ≥ 7.0 (minSdk 21) | `adb shell getprop ro.product.cpu.abi` → `arm64-v8a` |
| 2 | Débogage USB activé + hôte autorisé | `adb devices -l` → `… device usb:…` (**pas** `unauthorized`) |
| 3 | `adb` dans le `$PATH` | `which adb` |
| 4 | APK présent | `ls -l bin/transas-0.1-arm64-v8a-debug.apk` |
| 5 | PC sur le même réseau que le téléphone (**recommandé**) | nécessaire pour Nominatim/OSRM/tuiles OSM |

> **Constat du 2026-11-16 18:10** : le téléphone branché (`R3CX20LZVKA`) est en
> `unauthorized`. Tant que la popup n'est pas acceptée, **aucune** commande `adb
> shell`/`install` ne fonctionne. C'est le premier point bloquant de la recette.

### 1.1 Autoriser l'hôte (bloquant)

```bash
adb kill-server
adb start-server
adb devices -l
# → R3CX20LZVKA   unauthorized usb:2-2 transport_id:1
```

Sur le téléphone : popup **« Autoriser le débogage USB ? »** → cocher
« Toujours autoriser depuis cet ordinateur » → **OK**.

```bash
adb devices -l
# → R3CX20LZVKA   device usb:2-2 transport_id:1     ← attendu
adb shell getprop ro.product.model
adb shell getprop ro.build.version.release
```

Si la popup ne vient pas : débrancher/rebrancher le câble (câble **données**),
puis *Options développeur → Révoquer les autorisations de débogage USB* et
réessayer. Détails : `install.md` §3.1–§3.3.

### 1.2 Identifier l'installation existante

Le nom de package a changé dans l'historique ; vérifier **avant** d'installer :

```bash
adb shell pm path fr.transas.app.transas
# installé  → package:/data/app/~~…/fr.transas.app.transas-…/base.apk
# sinon     → Error: package not found
```

L'APK du 2026-11-16 porte le package **4 segments** `fr.transas.app.transas`
(identique au dernier build installé) : `adb install -r` conserve donc les
données (`transas.db`, cache de géocodage, cache de tuiles).

---

## 2. Installation

```bash
cd /home/el-hadj-ousmane/Bureau/trans_as

# 1. Vérifier l'APK qu'on installe (doit correspondre à l'en-tête de ce doc)
md5sum bin/transas-0.1-arm64-v8a-debug.apk

# 2. Installer par-dessus l'existant (données conservées)
adb install -r bin/transas-0.1-arm64-v8a-debug.apk
# → Success

# 3. Vérifier la version posée
adb shell dumpsys package fr.transas.app.transas | grep -E 'versionName|versionCode|lastUpdateTime'
```

| Message d'erreur | Cause | Action |
|---|---|---|
| `INSTALL_FAILED_UPDATE_INCOMPATIBLE` | APK signé avec une autre clé debug (autre machine) | `adb uninstall fr.transas.app.transas` puis réinstaller (perte des données) |
| `INSTALL_FAILED_VERSION_DOWNGRADE` | `versionCode` plus ancien que l'installé | `adb uninstall` puis réinstaller |
| `INSTALL_FAILED_INSUFFICIENT_STORAGE` | téléphone plein | libérer ≥ 100 Mo |
| `device unauthorized` | §1.1 non fait | accepter la popup |

---

## 3. Lancement + surveillance

Deux terminaux : **A** = logcat en continu, **B** = commandes.

```bash
# Terminal A — filtrer le bruit système
adb logcat -c
adb logcat '*:S' AndroidRuntime:E python:D Python:D Kivy:I crasher:E p4a:D \
  -v threadtime > /tmp/transas-safe-screen-$(date +%H%M).log

# Terminal B — lancer et vérifier la vie du process
adb shell am start -n fr.transas.app.transas/org.kivy.android.PythonActivity
# → Starting: Intent { cmp=fr.transas.app.transas/org.kivy.android.PythonActivity }

sleep 10 && adb shell pidof fr.transas.app.transas   # → un PID
sleep 110 && adb shell pidof fr.transas.app.transas  # → le MÊME PID
```

Écran attendu (portrait, thème navy/orange) :

```
[MENU]  TransAs                    0 arrêt  [OPTIONS]
┌──────────────────────────────────────────────────┐
│  carte OSM (Paris par défaut)        [+] [–]     │
└──────────────────────────────────────────────────┘
Ajoute des arrêts pour commencer la tournée.
[Départ………………] [Arrivée………………]
[Ajouter une adresse……………]            [+ STOP]
[            OPTIMISER L'ORDRE                  ]
```

**Échec immédiat si** dans le log : `FATAL BOOTSTRAP ERROR`, `Fatal signal 11`,
`dlopen failed: library "libpython3.11.so"`, ou `Start proc … transas` répété
≥ 3 fois en 5 s → passer à §6, ne pas insister.

---

## 4. Checklist fonctionnelle

Cocher au fur et à mesure ; noter le message de statut observé (colonne droite).

### T1 — Boot et stabilité
| Étape | Attendu |
|---|---|
| Lancer l'app, attendre 30 s | pas de crash, pas de clignotement d'écran |
| `pidof` à 10 s puis 2 min | PID identique |
| Basculer l'app en arrière-plan puis revenir | l'écran se réaffiche, pas de relance du splash |

### T2 — Carte OSM (tuiles)
| Étape | Attendu |
|---|---|
| Attendre ~2 s au boot | tuiles OSM visibles (rues, libellés lisibles), pas de damier vide |
| Appuyer sur `[+]` / `[–]` | zoom par crans, libellés rechargés |
| Deux doigts : pincer / glisser | zoom et déplacement, **le scroll de la page reste au doigt unique** |
| Passer en mode avion puis rouvrir la carte | tuiles déjà consultées servies depuis le cache ; pas de crash |

### T3 — Clavier et champs (le point le plus fragile)
| Étape | Attendu |
|---|---|
| Toucher « Ajouter une adresse » | le clavier s'ouvre, la carte et les listes se replient, le champ reste **visible au-dessus** du clavier |
| Taper `12 rue de Rivoli, 75001 Paris` | texte lisible, pas de champ caché |
| Appuyer sur **RETOUR** | le clavier se ferme, la mise en page se déploie (l'app ne quitte **pas**) |
| Toucher une zone hors champ avec le clavier ouvert | idem : clavier fermé, blocs restaurés |

### T4 — Ajout d'arrêts
| Étape | Attendu |
|---|---|
| `+ STOP` avec un champ vide | statut « Saisis une adresse avant d'ajouter un arrêt. » |
| Ajouter 3 adresses | statut « Arrêt #N ajouté — appuie sur OPTIMISER. » ; KPI « 0 livré · 3 en attente » ; 3 lignes avec « GPS à trouver » |

### T5 — Optimisation sans points fixes (départ = position actuelle)
| Étape | Attendu |
|---|---|
| `OPTIMISER L'ORDRE`, champ « Départ » vide, 1ʳᵉ fois | demande de permission Android ; « Autorise la localisation pour partir d'ici. » |
| Permission accordée | « Recherche de ta position… » puis « Géocodage… », « Matrice des distances… », « Optimisation… » |
| Fin | « Tournée optimisée depuis ta position · X,X km · OSRM » (ou `Haversine` si OSRM indisponible) ; lignes renumérotées ; « Prochain arrêt : … » |
| Permission refusée ou position introuvable | bascule sur une tournée sans départ fixe (« Calcul de la meilleure tournée… ») — pas de blocage |
| « Départ » saisi | la position n'est **pas** demandée ; le départ saisi est utilisé (voir T6) |

### T6 — Départ + arrivée fixes
| Étape | Attendu |
|---|---|
| Remplir **seulement** « Départ » puis optimiser | « Renseigne à la fois le départ et l'arrivée. » (bouton réactivé) |
| Remplir « Départ » **et** « Arrivée » puis optimiser | ordre commence par le départ, finit par l'arrivée, tous les arrêts présents une seule fois |

### T7 — Réoptimisation depuis la position (« RÉOPTIMISER D'ICI »)
| Étape | Attendu |
|---|---|
| `OPTIONS` → « Réoptimiser depuis ma position » | demande de permission Android (1ʳᵉ fois) |
| `OPTIMISER L'ORDRE` avec « Départ » vide | même départ temps réel (permission demandée), puis « Tournée optimisée depuis ta position · X,X km · OSRM » — cf. T5 |
| Autoriser | « Position trouvée — réoptimisation depuis ici… » puis tournée recalculée depuis le point GPS |
| Refuser la permission (tester après révocation) | « Localisation refusée — saisis le départ à la main. » — pas de crash |
| Refuser puis réessayer | « Autorise la localisation pour partir d'ici. » |

> Android 14+ : `adb shell setprop debug.*` est bloqué ; utiliser les file-flags
> `TRANSAS_SAFE_MODE` documentés dans `knowledge.md` si besoin de diagnostic.

### T8 — Import CSV / collé
| Étape | Attendu |
|---|---|
| `OPTIONS` → « Importer un fichier CSV » | popup « Importer des arrêts » |
| Coller 3 adresses (une par ligne) → `IMPORTER` | « 3 arrêts importés. Appuie sur OPTIMISER. » |
| Recoller les **mêmes** adresses | doublons non ajoutés (déduplication), compteur cohérent |
| Coller un CSV `Adresse;Ville` | la colonne `Adresse` est utilisée |

### T9 — Ajout par voix
| Étape | Attendu |
|---|---|
| `OPTIONS` → « Ajouter par voix » | « Écoute en cours : dicte l'adresse complète. » + écran de reconnaissance Android |
| Dicter une adresse | l'adresse reconnue est ajoutée directement à la liste (champ vidé) ; « Arrêt #N ajouté — appuie sur OPTIMISER. » |
| Annuler la dictée | message d'annulation dans la barre de statut, pas de crash |

### T10 — Navigation vers le prochain arrêt
| Étape | Attendu |
|---|---|
| `OPTIONS` → « Naviguer vers le prochain arrêt » | sélecteur d'apps (Maps/Waze/…) avec les coordonnées du 1ᵉʳ arrêt géocodé |
| Revenir dans TransAs (RETOUR) | l'app est intacte, la tournée inchangée |

### T11 — Livraison et persistance
| Étape | Attendu |
|---|---|
| `LIVRÉ` sur la 1ʳᵉ ligne | ligne retirée, KPI « 1 livré · N-1 en attente », prochain arrêt mis à jour |
| `adb shell am force-stop fr.transas.app.transas` puis relance | l'arrêt reste livré (persistance SQLite) |

### T12 — Profil conducteur
| Étape | Attendu |
|---|---|
| `MENU` → « Se connecter » → `ENREGISTRER` sans nom | le champ affiche « Le nom est requis » |
| Nom + e-mail → `ENREGISTRER` | « Profil enregistré : <nom>. » |
| Relancer l'app | le profil est toujours présent (`<db>.profile.json`) |

### T13 — Partage / impression (informatif)
| Étape | Attendu |
|---|---|
| `OPTIONS` → « Partager le trajet » | sélecteur Android avec le texte de la tournée (départ, arrêts numérotés, arrivée) |
| `OPTIONS` → « Imprimer le trajet » | service d'impression / export PDF |

### T14 — Suppression
| Étape | Attendu |
|---|---|
| `OPTIONS` → « Supprimer les arrêts » → `ANNULER` | rien n'est supprimé |
| Recommencer → `SUPPRIMER` | « Tous les arrêts en attente ont été supprimés. », liste et KPI vidés |

### T15 — Nouveau trajet
| Étape | Attendu |
|---|---|
| Saisir départ/arrivée, puis `MENU` → « Créer un nouveau trajet » | « Nouveau trajet prêt : ajoute tes arrêts. », champs Départ/Arrivée vidés |

### T16 — Robustesse réseau
| Étape | Attendu |
|---|---|
| Mode avion, ajouter un arrêt, `OPTIMISER L'ORDRE` | bascule `Haversine`, message d'erreur explicite ou tournée calculée — **pas** de crash |
| Rétablir le réseau puis réoptimiser | retour à `OSRM` |

---

## 5. Journal de recette (à remplir / joindre au retour)

| Test | Résultat (OK / KO) | Message observé | Remarque |
|------|--------------------|-----------------|----------|
| T1 boot 2 min | | | |
| T2 tuiles + gestes | | | |
| T3 clavier + RETOUR | | | |
| T4 ajout d'arrêts | | | |
| T5 optimisation | | | |
| T6 départ/arrivée | | | |
| T7 GPS | | | |
| T8 import | | | |
| T9 voix | | | |
| T10 navigation | | | |
| T11 livré + persistance | | | |
| T12 profil | | | |
| T13 partage/impression | | | |
| T14 suppression | | | |
| T15 nouveau trajet | | | |
| T16 hors-ligne | | | |

Appareil : `________` · Android : `________` · GPU : `________` ·
APK md5 : `________` · Date : `________`

---

## 6. Diagnostic si ça casse

```bash
# Crash dur (tombstone + stack Java)
adb logcat -b crash -d | tail -80

# Tout ce qui concerne TransAs / Kivy / Python
adb logcat -d -v threadtime | grep -Ei 'transas|python|kivy|SIGSEGV|Adreno|GLES|FATAL' | tail -120

# L'app tourne-t-elle encore ?
adb shell pidof fr.transas.app.transas

# Version réellement installée
adb shell dumpsys package fr.transas.app.transas | grep -E 'versionName|firstInstallTime|lastUpdateTime'
```

| Symptôme | Cause probable | Action |
|---|---|---|
| `Fatal signal 11 … fault addr 0x28` dans `libGLESv2_adreno.so` | BUG-010 (driver Adreno), hors de portée Python | noter le GPU, joindre le log, ne pas monkey-patcher |
| `FATAL BOOTSTRAP ERROR` (tag `python`) | exception Python au démarrage | le traceback complet est dans le log — le remonter tel quel |
| `No module named 'X'` | dépendance absente du rebuild | rebuild `clean` (`buildozer android clean && buildozer android debug`) |
| Tuiles grises / HTTP 403 | User-Agent OSM absent ou modifié | vérifier `config.TILE_USER_AGENT` |
| Popup permission absente | permission déjà refusée « Ne plus demander » | *Paramètres → Apps → TransAs → Autorisations → Position* |
| `Error type 3: Activity class does not exist` | mauvais package | `adb shell pm path fr.transas.app.transas` puis relancer avec le nom exact |
| Clavier qui recouvre le champ | `softinput_mode` non appliqué | vérifier `main._enable_soft_keyboard_panning()` dans le log `transas.bootstrap` |

---

## 7. Rollback et nettoyage

Aucun APK de safety-net validé ne subsiste dans `bin/` : il a été écrasé par le
build du 2026-11-16. Pour revenir à un état connu :

```bash
# Option A — APK incrémental du jour (même code Python, libs natives du 26/10)
adb install -r /tmp/transas-debug-incremental-ndk28.apk   # md5 06c888839c6c771dd5faa2c043a2ebec

# Option B — reconstruire depuis le commit précédent (recommandé si régression)
git stash            # si des modifs locales
git checkout 62926c7 # dernier commit avant le nouvel écran
buildozer android clean && buildozer android debug
```

Sauvegarde des données de test avant désinstallation (build debug uniquement) :

```bash
adb shell run-as fr.transas.app.transas cat files/transas.db > /tmp/transas-test.db
adb uninstall fr.transas.app.transas      # efface DB, cache géocodage et tuiles
```

Après la recette :

```bash
adb logcat -d > /tmp/transas-rectte-$(date +%F).log   # joindre au rapport
adb shell am force-stop fr.transas.app.transas
```
