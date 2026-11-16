# Installation TransAs sur téléphone Android personnel — guide pas-à-pas

> **Public** : toi / un dev qui veut tester l'APK `bin/transas-0.1-arm64-v8a-debug.apk`
> sur son propre téléphone avant qu'une version signée release existe.
>
> **Date** : 2026-07-13
>
> **Contexte** : le repo TransAs est **privé** ; aucun risque de distribution
> involontaire avec un APK signé-debug.

---

## 1. Pré-requis côté téléphone

À vérifier une seule fois par téléphone, persistant après reboot :

| # | Action | Chemin dans les paramètres Android |
|---|--------|-----------------------------------|
| 1 | Activer le **mode développeur** | `Paramètres > À propos du téléphone` → taper **7 fois** sur « Numéro de build » |
| 2 | Activer le **débogage USB** | `Paramètres > Options pour les développeurs > Débogage USB` ☐ → ☑ |
| 3 | Brancher le câble USB **données (pas charge-only)** | — |
| 4 | Sur le téléphone, **changer le mode USB** en « Transfert de fichiers (MTP) » ou « PTP » si demandé | Notification système après branchement |
| 5 | Vérifier l'architecture CPU du téléphone | `adb shell getprop ro.product.cpu.abi` doit renvoyer **`arm64-v8a`** (tous les téléphones ≥ 2018) |

## 2. Pré-requis côté PC

| # | Action | Comment |
|---|--------|---------|
| 1 | Avoir `adb` dans le `$PATH` | Livré avec `android-sdk/platform-tools`. Test : `which adb` |
| 2 | Avoir le SDK NDK + cmdline-tools en place | Sinon suivre `knowledge.md` § "APK build prerequisites" |
| 3 | Avoir `bin/transas-0.1-arm64-v8a-debug.apk` (~28 MB) | Produit par iter-36 (`a0c18d7`) en CI |

## 3. Premier contact adb — le bug « device unauthorized »

Quand tu branches un nouveau téléphone pour la première fois, adb **refuse** de pousser
quoi que ce soit tant que le téléphone n'a pas accepté ton PC comme hôte de confiance.
Tu vas voir :

```text
$ adb install bin/transas-0.1-arm64-v8a-debug.apk
adb: device unauthorized.
This adb server's $ADB_VENDOR_KEYS is not set
Try 'adb kill-server' if that seems wrong.
Otherwise check for a confirmation dialog on your device.
```

### 3.1 — Cas normal : pas de `~/.android/adbkey` côté PC

C'est **le cas attendu** sur ce projet. Le warning `$ADB_VENDOR_KEYS is not set` est
juste informatif — il indique que le serveur adb n'a pas de clé publique personnelle à
utiliser pour signer son challenge RSA. Ça ne bloque pas l'authentification, c'est la
**confirmation sur le téléphone** qui bloque.

**Procédure** :

```bash
# 1. Tuer le serveur adb (force le redémarrage propre)
adb kill-server

# 2. Vérifier que le téléphone est bien branché
lsusb | grep -i 'android\|google\|samsung\|xiaomi\|huawei\|oneplus\|fairphone'
# Attendu : "Bus 001 Device 005: ID 18d1:4ee7 Google Inc. Nexus/Pixel (MTP+ADB)"

# 3. Re-démarrer le serveur adb
adb start-server

# 4. Réessayer (avec -l pour voir l'USB-id + le manufacturer)
adb devices -l
# Attendu : "R5CT70ABCDE       unauthorized usb:1-1.4  Google_Pixel_5"

# 5. Sur le téléphone, un POPUP apparaît :
#    "Allow USB debugging from this computer?"
#    ▢ Ne plus demander pour cet ordinateur
#    [Annuler]  [OK]
#    → TOUCHE **OK** (et coche aussi la case si tu veux éviter le popup à chaque fois)

# 6. Re-vérifier
adb devices -l
# Attendu : "R5CT70ABCDE       device usb:1-1.4  Google_Pixel_5"  ← authorized confirmé
```

### 3.2 — Cas spécial : tu utilises plusieurs PC

Si tu switch souvent entre ton PC perso, ton laptop, un CI runner, chacun doit
apparaitre dans la liste USB-debugging du téléphone :

```
Paramètres > Options pour les développeurs > Révoquer les autorisations de débogage USB
```

→ tu revois le popup à la prochaine connexion suivante.

### 3.3 — Cas très rare : câble USB défectueux

Si `adb devices` retourne **rien du tout** (phone pas listé), c'est généralement :

- Câble **charge-only** (pas de broches data) → utilise un autre câble
- Port USB foireux sur le PC → essaie un autre port
- Phone verrouillé en mode **fastboot** au lieu de Recovery/Android → reboot normal

## 4. Installation effective

```bash
cd /home/el-hadj-ousmane/Bureau/trans_as

# 0. D'ABORD — identifier ce qui est installé (CRUCIAL après un changement de buildozer.spec)
#
# On recommande ci-dessous 3 méthodes de la plus fiable à la plus legacy. La
# méthode `pm path` est **préférée** : pas de SecurityException sur les profils
# multi-user, échec propre avec "package not found", syntaxe identique partout.
#
# ⚠️  GOTCHA MULTI-USER : si tu vois "java.lang.SecurityException: Shell does not
#    have permission to access user 150", c'est un profil "travail" / "managed
#    profile" sur ton tel qui bloque le listing global. Utilise la Méthode 1
#    ci-dessous (pas de listing) ou la Méthode 2 (limitée à user 0).
#
# Méthode 1 — RECOMMANDÉE : test direct par nom, échoue proprement si pas installé
#   adb shell pm path fr.transas.app
# Attendu si installé : "package:/data/app/~~XYZ==/fr.transas.app-ABC==/base.apk"
# Attendu si pas installé : "Error: package not found"
#
#   adb shell pm path fr.transas.app.transas   # test de l'ancien nom (4-segs)
#
# Méthode 2 — listing filtré au user 0 (si tu veux voir TOUS les packages TransAs)
adb shell pm list packages --user 0 | grep transas
#
# Méthode 3 — listing global (LEGACY, peut crasher avec SecurityException)
#   adb shell pm list packages | grep transas
#
# Sortie typique (UN SEUL des deux sera présent) :
#   package:fr.transas.app.transas   ← ancien APK (4 segments, builds avant le fix de buildozer.spec)
#   package:fr.transas.app            ← nouvel APK (3 segments, après rebuild avec le nouveau spec)
# Si rien n'est listé : APK pas encore installé → passer à l'étape 3 directement.
# Si l'AUTRE nom (que celui attendu) est listé : `adb uninstall <le.mauvais.nom>` puis revenir ici.

# 1. Vérifier que le téléphone est prêt
adb devices
# Attendu : "R5CT70ABCDE   device"

# 2. (optionnel — pour diagnostic) architecture + Android version
adb shell getprop ro.product.cpu.abi    # → "arm64-v8a"
adb shell getprop ro.build.version.sdk  # → ≥ 21 (minAPI buildozer.spec)
adb shell getprop ro.build.version.release  # → ex "14" (Android version)

# 3. Installer l'APK
adb install bin/transas-0.1-arm64-v8a-debug.apk
# Variante -r si tu réinstalles par-dessus une version existante
adb install -r bin/transas-0.1-arm64-v8a-debug.apk

# 4. Lancer l'app (NB : utilise le nom EXACT retourné par `pm list packages` à l'étape 0.
#    Si tu vois "Error type 3: Activity class {…} does not exist", c'est un mismatch de nom —
#    NE REBOUTE PAS, retourne à l'étape 0 et utilise le bon nom.)
adb shell am start -n <le.package.retourné.par.pm.list.packages>/org.kivy.android.PythonActivity
# Exemples :
#   adb shell am start -n fr.transas.app/org.kivy.android.PythonActivity
#   adb shell am start -n fr.transas.app.transas/org.kivy.android.PythonActivity
#
# Variante auto — sous-shell bash/zsh qui substitue le nom dynamiquement :
#   PKG=$(adb shell pm list packages | grep transas | head -1 | sed 's/^package://;s/\r$//')
#   adb shell am start -n "${PKG}/org.kivy.android.PythonActivity"

# 5. Vérifier que l'app est bien vivante (process-level, portable Android)
adb shell pidof fr.transas.app
# Attendu : "12345"  (PID du process PythonActivity)
```

## 5. Diagnostics en cas de crash au launch

```bash
# ⚠️  NOTE ZSH : si tu es sur zsh (macOS par défaut), tu DOIS quoter le `*` sinon zsh
# tente de l'expanser comme un glob et crashe avec `zsh: no matches found: *:S`.
# Les 2 variantes ci-dessous sont syntaxiquement équivalentes (silence + tags surchargés)
# et marchent sur bash ET zsh :

# Variante 1 — guillemets simples autour du pattern silence (la plus lisible)
adb logcat '*:S' AndroidRuntime:E python:D Python:D Kivy:D crasher:E p4a:D -v threadtime > /tmp/transas-crash.log

# Variante 2 — escape du `*` avec backslash (équivalent, plus cryptique)
adb logcat \*:S AndroidRuntime:E python:D Python:D Kivy:D crasher:E p4a:D -v threadtime > /tmp/transas-crash.log

# Variante "vue d'ensemble" (filtrage texte après capture) — bash/zsh-safe
adb logcat -d -v threadtime | grep -E 'python|Python|Kivy|FATAL|AndroidRuntime|transas' | head -80 > /tmp/transas-crash-wide.log

# Patterns typiques à chercher :
#   - "FATAL EXCEPTION: main"  → crash dur, full stack à inspecter
#   - "sqlite3.OperationalError"  → DB path problème (cf. main.py:_writable_dir)
#   - "Material Design Icons" / "KivyMD: missing font"  → MDUI assets manquants
#   - "java.io.FileNotFoundException"  → asset path cassé (MapScreen ui/_runtime_map.png)
#   - "dlopen failed: library \"libpython3.11.so\" not found"  → casse-native
#   - "Cannot find module 'folium'" ou "No module named 'X'"  → requirements manquant
#   - "cannot identify image file" / "UnidentifiedImageError"  → Pillow decode fail (MapScreen)
#   - "CalledProcessError"  → subprocess p4a bootstrap crash (rare, vu sur NDK r25c)
#   - "Start proc" répété pour fr.transas.app qui ne stabilise jamais
#     (heuristique : compter "Start proc.*fr.transas.app" sur 5 s ;
#     ≥ 3 occurrences = crash natif avant init Python, souvent libpython ou Pillow)
```

Si tu vois un crash, **pas de panique** : ça n'atteint pas les data perso. Désinstalle,
fix, rebuild, réinstall. Itération rapide — voir §7.

## 6. Désinstallation (wipe complet avant de réinstaller signed-release)

### 6.0 — D'ABORD : identifier le package actuellement installé

Le nom de package a changé plusieurs fois dans l'historique du projet. Avant
de désinstaller, **identifie quel APK est actuellement sur ton tel** :

```bash
# Voir tous les packages TransAs installés (historique)
adb shell pm list packages | grep transas
# Sortie typique (un seul des deux sera présent) :
#   package:fr.transas.app.transas   ← ancien APK (4 segments, p4a name+domain inversé)
#   package:fr.transas.app            ← nouvel APK (3 segments, après ce fix)
```

Puis désinstalle **celui qui est listé** (pas l'autre) :

```bash
# Si c'est l'ancien :
adb uninstall fr.transas.app.transas

# Si c'est le nouveau :
adb uninstall fr.transas.app
```

### 6.1 — Wipe total (après identification)

```bash
# Wipe total — signature debug évaporée
adb uninstall fr.transas.app
# Attendu : "Success"

# ⚠️ Cette commande efface aussi :
#   - la base SQLite transas.db   (`/data/data/fr.transas.app/files/transas.db`)
#   - le cache Nominatim          (`/data/data/fr.transas.app/files/.cache/geocoding_cache.json`)
#   - preferences partagées
```

Si tu veux **préserver des données de test** avant de désinstaller :

```bash
# 1. Backup (valable pour build debug = `android:debuggable=true`)
#    Note technique : `main.py:_writable_dir()` résout `app.user_data_dir` sur
#    Android à `/data/data/fr.transas.app/files/`. Le DB SQLite est donc à :
adb shell run-as fr.transas.app cat files/transas.db > /tmp/transas-test.db
#    (ne PAS utiliser `databases/transas.db` : SQLite n'est pas systématiquement
#    créé dans le sous-dossier `databases/` — p4a suit le schéma `files/`)

# 2. Désinstaller
adb uninstall fr.transas.app

# 3. Installer la version signed-release (quand dispo)
adb install transas-0.1-arm64-v8a-release.apk
```

(`run-as` ne marche **que** sur build debug — sur release build, Android refuse. Si tu as
besoin de persister entre install, utilise la procédure F-Droid-grade + cloud sync,
out of scope ici.)

## 7. Réinstallation signed-release (futur, après P0 fait)

Quand `REPORT.md` P0 (signature release activée) sera terminé, tu auras 2 APK :

| Fichier | Source | Signature |
|---------|--------|-----------|
| `bin/transas-0.1-arm64-v8a-debug.apk` | Ton build local ou CI `pull_request` | Debug keystore (volatile) |
| `bin/transas-0.1-arm64-v8a-release.apk` | CI tag `vX.Y.Z` uniquement | `transas-release.jks` (stable) |

Le passage install → uninstall → install passant du **debug** au **release** est **toujours
valide** (cf. §6) car le `adb uninstall` ne préserve rien → la signature debug est totalement
évaporée, et le `release.apk` est une fresh install.

⚠️ **Converse** : passer du **release au debug** est INTERDIT par Android sans uninstall
préalable. C'est pour ça qu'on ne livre jamais un release avant que le debug soit validé.

## 8. Workflow complet — checklist pratique

```text
[ ] Téléphone : mode développeur activé
[ ] Téléphone : débogage USB activé
[ ] Téléphone : USB en mode MTP/PTP
[ ] PC : adb dans $PATH
[ ] PC : APK présent dans bin/
[ ] bash adb kill-server && adb start-server
[ ] adb devices → "unauthorized" en premier, puis popup téléphone → OK, puis "device"
[ ] adb shell pm list packages | grep transas → noter le nom EXACT (fr.transas.app OU fr.transas.app.transas)
[ ] adb install bin/transas-0.1-arm64-v8a-debug.apk
[ ] adb shell am start -n <nom.noté.ci.dessus>/org.kivy.android.PythonActivity
[ ] UI : vérifier que SafeTransAsScreen s'affiche (MENU / TransAs / OPTIONS + carte OSM)
[ ] Recette fonctionnelle complète : suivre `docs/INSTALL_TEST_SAFE_SCREEN.md`
[ ] Si crash : `adb logcat '*:S' AndroidRuntime:E python:D Python:D Kivy:D crasher:E p4a:D -v threadtime > /tmp/launch.log` (zsh : quoter le `*`) → m'envoyer le contenu pour diagnostic
[ ] Quand fini : adb uninstall <le.même.nom.que.lancé> (wipe complet)
[ ] Plus tard, quand signed-release dispo : adb install transas-*-release.apk
```

## 9. Liens de référence

- `REPORT.md` §6 + §9 — actions P0/P1/P2/P3 (signature release + kivymd fix + chemin vers APK signé)
- `knowledge.md` § "APK build prerequisites" — toolchain complet pour rebuilder en local
- `.gitignore` (à la racine) — pourquoi le dossier `bin/` n'est PAS versionné (rebuild à chaque fois via `buildozer android debug`)
- `cover/README.md` § Prerequisite toolchain — variantes macOS / Windows si tu changes de machine
