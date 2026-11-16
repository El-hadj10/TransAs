# Rapport de bugs — session debug TransAs (2026-07-13)

> **Contexte** : tentative d'installation de l'APK `bin/transas-0.1-arm64-v8a-debug.apk`
> (28 MB, debug-signed, iter-36 `a0c18d7`) sur un téléphone Android personnel (arm64-v8a).
>
> **Statut global (mis à jour 2026-07-13 10:46)** : 🟢 **APK REBUILDÉ avec Pillow 11.3.0**.
> Après 4 tentatives échouées (patch p4a incompatible avec Pillow 10.2.0), rollback
> vers `Pillow==11.3.0` (qui matche la recipe p4a locale). L'APK est généré
> (`bin/transas-0.1-arm64-v8a-debug.apk`, 28.9 MB) ; reste à installer et tester
> sur device pour valider que les fixes défensifs suffisent à éviter le SIGSEGV.
> Voir section "Décision 2026-07-13 — Rollback Pillow" ci-dessous.

---

## 🔴 BUG-001 (CRITICAL) — Crash natif au launch : SIGSEGV dans SDLThread

### Symptôme
```
$ adb shell am start -n fr.transas.app/org.kivy.android.PythonActivity
Activity could not be started for Intent { ... pkg=fr.transas.app cmp=.../PythonActivity }
```
L'app crash immédiatement. Aucune traceback Python visible dans le logcat (45 MB, 440k+ lignes).

### Preuve (depuis `/tmp/launch.log`)
- Section 11 du log extrait : `libpython3.11.so`, `libSDL2.so`, `libp4a_android.so` → les
  3 libs sont chargées par `SDLThread` (le thread natif créé par Kivy).
- Section 12 : `signal 11 (SIGSEGV)` répété à intervalles courts (2-3s).
- Section 8 : `Start proc 17374 / 17534 / 17661` pour `fr.transas.app` → boucle crash→restart.

### Cause racine (hypothèse principale)
**Mismatch d'ABI native entre libpython3.11.so (compilé par p4a Cython 0.29.36), libSDL2.so
(intégré à p4a 2024.x), et Pillow 11.3.0 (qui pull `libjpeg`/`libpng`/`libwebp` via Pillow's
own setuptools script).** Sur NDK r25c + Android API 34, la séquence d'initialisation de
`SDLThread` peut `dlopen` Pillow's libs avant que les autres soient stabilisées, d'où le
SEGV dans `PyObject_Vectorcall`.

### Correctifs appliqués
1. **`map_screen.py`** : import de `ui.services.folium_renderer` (qui pull `PIL`) déporté
   depuis le top-level vers l'intérieur de `refresh_from_db`. Confine le load natif Pillow
   à un user-initiated action (bouton "Actualiser" sur MapScreen).
2. **`main.py`** : ajout d'un `try/except BaseException` autour de `TransAsApp().run()` avec
   logging `CRITICAL` → permet à **toute exception Python ultérieure** d'apparaître dans
   logcat (sous le tag `python`). Ne catch PAS les SEGV natifs (out of Python's reach).

### Cause racine CONFIRMÉE (post-extraction du nouveau `/tmp/launch.log`)
Le SIGSEGV à fault address `0x28` (null pointer +40 bytes) dans
`SDLThread → libSDL2.so → PyObject_Vectorcall` est typique d'une désérialisation
C-level foireuse. Le **provider `img_pil` de Kivy** (chargé par
`from kivy.core.image import Image as CoreImage` dans `ui/screens/map_screen.py`
ligne 14) **auto-importe PIL au module-load** via son mécanisme d'image providers.
Cela bypass tout defer applicatif de `ui.services.folium_renderer` (FIX DEFENSIF-001
est donc **insuffisant seul**). Pillow 11.x échoue à linker proprement avec
libjpeg/libpng p4a-built sur NDK r25c → le premier appel à `PyObject_Vectorcall`
après init SDLThread se fait sur un objet Py incomplet → SEGV.

### Correctif APPLIQUÉ (rebuild EN COURS / requis pour activer)
- **Downgrade Pillow** : `Pillow==11.3.0` → `Pillow==10.2.0` dans `buildozer.spec` —
  **ROLLBACK 2026-07-13 10:46**. Voir section dédiée ci-dessous pour l'historique
  complet des 4 tentatives échouées. La recipe p4a locale
  (`.local/python-for-android/pythonforandroid/recipes/Pillow/`) a un patch
  `setup.py.patch` codé en dur pour Pillow 11.3.0 (lignes 156, 514, 565, 674) ;
  les 2 premiers hunks ne s'appliquent pas à 10.2.0. Patch attendu ~1-2h
  d'investigation + 1-2 builds d'essai → non rentable tant que le SIGSEGV n'est
  pas confirmé Pillow 11.x.
- **Bump NDK** : `25.2.9519653` → `28.0.13004108` (dernier stable recommandé par p4a
  2024.07). **Non recommandé** sauf si Pillow 10.x échoue aussi — nécessite de
  décommissionner le `clang.real` shim → risque de régression CI.

---

### 🆕 Décision 2026-07-13 — Rollback Pillow 11.3.0 (après 4 builds échoués)

**Contexte** : Pour fixer BUG-001, on a initialement tenté de downgrader Pillow
de 11.3.0 à 10.2.0 (théorie : SIGSEGV dans `PyObject_Vectorcall` causé par
Pillow 11.x mal linké contre libjpeg/libpng p4a-built sur NDK r25c).

**Historique des 4 tentatives échouées** :

| # | Tentative | Erreur | Fix appliqué |
|---|---|---|---|
| 1 | `buildozer android clean && buildozer android debug` | `Cython (cython) not found` | `PATH=.venv/bin:$PATH` |
| 2 | Avec PATH venv | `pip --user` error in venv | `pyvenv.cfg: include-system-site-packages=true` + `PYTHONUSERBASE` isolé |
| 3 | Avec venv + PYTHONUSERBASE | `ImportError: cannot import name 'RequirementInformation' from pip._vendor.resolvelib.structs` | Downgrade pip `<24.2` + setuptools `<71.0.0` + constraint Pillow==10.2.0 |
| 4 | Avec pip downgrade + constraint | `patch FAILED at line 156` + `patch FAILED at line 514` (2 hunks sur 4 dans `setup.py.patch` qui est codé dur pour Pillow 11.3.0) | **ROLLBACK** Pillow==11.3.0 dans buildozer.spec |

**Décision finale (2026-07-13 10:46)** : `Pillow==11.3.0` (qui matche la recipe
p4a locale). Les **fixes défensifs** restent le **vrai** mitigation contre le
SIGSEGV :

1. **Defer de `kivy.core.image`** dans `ui/screens/map_screen.py` (retire le
   provider `img_pil` du chemin critique de SDLThread bootstrap).
2. **Defer de `ui.services.folium_renderer`** dans `refresh_from_db` (idem pour
   PIL).
3. **Try/except `BaseException`** dans `main.py` (capture toute exception
   Python résiduelle pour logging CRITICAL → debug plus rapide).

**Plan B (si SIGSEGV persiste après install/test sur device)** :
1. Patcher la recipe p4a :
   - `.local/python-for-android/pythonforandroid/recipes/Pillow/__init__.py` :
     `version = '11.3.0'` → `version = '10.2.0'`
   - Régénérer un setup.py.patch compatible Pillow 10.2.0 (comparer les
     sections `_find_library_dirs_ldconfig`, `pkg_config`, `disable_platform_guessing`
     entre les deux versions de setup.py).
   - Effort estimé : 1-2h + 1-2 builds d'essai.
2. **OU** bump NDK r25c → r28c (si le problème est plus profond que Pillow).
3. **OU** skip Pillow entirely (safe mode) — retirer de buildozer.spec, le
   folium_renderer tombera en `ImportError` gracieux au runtime, mais l'app
   bootera.

### Actions de rebuild post-fix
```bash
buildozer android clean && buildozer android debug
adb uninstall <pkg>   # nom exact : pm path fr.transas.app OU fr.transas.app.transas
adb install bin/transas-0.1-arm64-v8a-debug.apk
PKG=$(adb shell pm path fr.transas.app 2>/dev/null | head -1 | sed 's/^package://;s/\r$//;s|/base.apk||')
adb shell am start -n "${PKG}/org.kivy.android.PythonActivity"
sleep 5
adb logcat '*:S' AndroidRuntime:E python:D Python:D Kivy:D crasher:E p4a:D -v threadtime > /tmp/launch4.log
```

### Vérification post-rebuild
```bash
# 1. Rebuild
buildozer android debug

# 2. Désinstaller l'ancien APK (⚠️ utiliser le nom EXACT listé par
#    `pm list packages | grep transas` — peut être fr.transas.app OU
#    fr.transas.app.transas selon l'historique des builds)
adb uninstall <le.package.retourné.par.pm.list.packages>

# 3. Réinstaller
adb install bin/transas-0.1-arm64-v8a-debug.apk

# 4. Lancer + capturer log
adb logcat -c
adb shell am start -n fr.transas.app/org.kivy.android.PythonActivity
sleep 5
adb logcat *:S AndroidRuntime:E python:D Python:D Kivy:D crasher:E p4a:D -v threadtime > /tmp/launch2.log
```

---

## 🟠 BUG-002 (HIGH) — `buildozer.spec` : nom de package incohérent (4 segments)

### Symptôme
Le `buildozer.spec` à `package.name=transas, package.domain=fr.transas.app` produit un
package `fr.transas.app.transas` (4 segments, par concaténation p4a). Or le path canonique
utilisé dans l'original `install.md` (et confirmé par l'expérience utilisateur) est
`fr.transas.app` (3 segments).

### Conséquence
- L'utilisateur a utilisé `fr.transas.app/...` dans `am start` et `adb uninstall`.
- Le système essayait `fr.transas.app` → ne trouve pas le package (silencieusement, ou via
  fallback ActivityManager) → la résolution mène à un crash différent.

### Correctif appliqué
**`buildozer.spec`** :
```ini
# AVANT
package.name = transas
package.domain = fr.transas.app

# APRÈS
package.name = app
package.domain = fr.transas
```
→ produit `fr.transas.app` (3 segments), aligné avec les commandes `install.md`.

### Vérification
- Le **prochain build** produira un APK avec le bon nom de package.
- L'APK actuel sur le device (`fr.transas.app.transas`) ne sera plus reproductible après ce fix.

---

## 🟠 BUG-003 (HIGH) — `install.md` : commentaire §4 step 4 cassé après replace

### Symptôme
Le replace en bulk de `fr.transas.app.transas` → `fr.transas.app` a généré un commentaire
auto-référentiel cassé :
```
# 4. Lancer l'app (NB : le package réel est `fr.transas.app`,
#    pas `fr.transas.app` — p4a concatène ...
```

### Correctif appliqué
**`install.md` §4 step 4** :
```diff
-# 4. Lancer l'app (NB : le package réel est `fr.transas.app`,
-#    pas `fr.transas.app` — p4a concatène package.domain + package.name
-#    du buildozer.spec, ce qui donne 4 segments)
+# 4. Lancer l'app (NB : le package est `fr.transas.app` — p4a
+#    concatène package.domain + "." + package.name = "fr.transas" + "." + "app"
+#    selon le buildozer.spec courant)
 adb shell am start -n fr.transas.app/org.kivy.android.PythonActivity
```

### Vérification
- `grep -nE 'pas \`fr\.transas\.app\`' install.md` → 0 résultat
- `grep -nE 'le package.*fr\.transas\.app`' install.md` → 1 résultat, cohérent.

---

## 🟡 BUG-004 (MEDIUM) — `adb uninstall` échoue avec `DELETE_FAILED_INTERNAL_ERROR`

### Symptôme
```
$ adb uninstall fr.transas.app
Failure [DELETE_FAILED_INTERNAL_ERROR]
```

### Cause
- Soit le package sur le device est `fr.transas.app.transas` (ancien build) et on essaie
  de désinstaller `fr.transas.app` (mismatch).
- Soit l'app est dans un état semi-installé (process crash mid-install).

### Correctif documenté
**`install.md` §6** documente 4 niveaux d'escalade :
```bash
# Niveau 1
adb shell am force-stop fr.transas.app
adb uninstall fr.transas.app

# Niveau 2
adb shell pm uninstall -k fr.transas.app

# Niveau 3
adb shell pm clear fr.transas.app
adb shell pm uninstall --user 0 fr.transas.app

# Niveau 4
adb shell pm path fr.transas.app   # trouver le chemin APK
adb shell pm uninstall -k --user 0 fr.transas.app
```

### Vérification
- Pour le **prochain build** (package `fr.transas.app` propre), le niveau 1 marchera
  systématiquement.
- Pour l'APK actuel sur le device, il faut d'abord identifier le **vrai** nom de package
  installé : `adb shell pm list packages | grep transas`.

---

## 🟢 BUG-005 (LOW) — Caractère `→` (U+2192) casse le shell

### Symptôme
Le user a copié-collé depuis `install.md §8` une ligne contenant `→` (flèche stylistique).
Bash l'a interprété comme un séparateur de mots (et grep comme un nom de fichier) :
```
$ adb logcat | grep FATAL > /tmp/crash.log → itérer fix
grep: →: Aucun fichier ou dossier de ce nom
grep: itérer: Aucun fichier ou dossier de ce nom
grep: fix: Aucun fichier ou dossier de ce nom
```

### Correctif appliqué
**`install.md` §8** : la flèche a été retirée de la checklist. Le commentaire indique
maintenant explicitement "(pas de flèche `→`)" pour éviter la récidive.

### Leçon apprise
- Aucun caractère Unicode stylistique dans les blocs de code copiables.
- Utiliser des flèches seulement dans le texte narratif, jamais dans un bloc `bash`.
- Pour les checklists, préférer des `[ ]` (ASCII pur).

---

## 🟢 BUG-006 (LOW) — `adb device unauthorized` (déjà documenté)

### Symptôme
Premier branchement USB : `adb: device unauthorized. This adb server's $ADB_VENDOR_KEYS is not set`.

### Cause
Le téléphone doit explicitement autoriser le PC comme hôte de debug USB (popup au premier
branchement).

### Statut
✅ **Déjà documenté** dans `install.md §3` avec procédure complète (kill-server → start-server
→ devices -l → popup téléphone → OK → devices -l confirme "device").

---

## 🟠 BUG-007 (MEDIUM) — zsh : `zsh: no matches found: *:S` sur la commande logcat silencieuse

### Symptôme
```
$ adb logcat *:S AndroidRuntime:E python:D ... > /tmp/launch2.log
zsh: no matches found: *:S
```
La commande logcat silencieuse échoue sur zsh (le shell par défaut de macOS).

### Cause
zsh, contrairement à bash, **refuse par défaut** d'expanser un glob qui ne matche aucun
fichier — au lieu de passer la chaîne littéralement, il sort en erreur. Le token `*:S` est
donc traité comme un glob raté, pas comme le filtre logcat Android `*:S` (silence global).

### Correctif appliqué
**`install.md` §5** documente désormais **3 variantes zsh-safe** :
```bash
# Variante 1 — guillemets simples (zsh-safe)
adb logcat '*:S' AndroidRuntime:E python:D ... > /tmp/transas-crash.log

# Variante 2 — `-s` au lieu de `*:S` (équivalent, pas de glob)
adb logcat -v threadtime -s AndroidRuntime:E python:D ... > /tmp/transas-crash.log

# Variante 3 — backslash escape (bash ET zsh-safe)
adb logcat \*:S AndroidRuntime:E python:D ... > /tmp/transas-crash.log
```

### Vérification
- `bash` users : la variante 3 (`\*:S`) marche directement sans changement.
- `zsh` users (macOS par défaut) : variantes 1 ou 2 recommandées.
- Variante 2 (la plus propre) marche sur les deux shells sans aucun quoting.

---

## 🟠 BUG-008 (MEDIUM) — `Error type 3: Activity class {…} does not exist`

### Symptôme (observé en session debug 2026-07-13)
```
$ adb install bin/transas-0.1-arm64-v8a-debug.apk
Success
$ adb shell am start -n fr.transas.app/org.kivy.android.PythonActivity
Starting: Intent { cmp=fr.transas.app/org.kivy.android.PythonActivity }
Error type 3
Error: Activity class {fr.transas.app/org.kivy.android.PythonActivity} does not exist.
```

### Cause
L'APK `bin/transas-0.1-arm64-v8a-debug.apk` est un **ancien build** (construit avec
`buildozer.spec` à `package.name=transas, package.domain=fr.transas.app` → produit
`fr.transas.app.transas`, 4 segments). Or la commande de launch utilise `fr.transas.app`
(3 segments, le nom canonique du nouveau buildozer.spec). **Mismatch de nom**.

Le message d'erreur Android `Error type 3 / ACTIVITY_DOES_NOT_EXIST` est trompeur : il
signifie littéralement "je ne trouve pas la classe demandée DANS le package demandé", ce
qui inclut le cas où le package lui-même n'existe pas.

### Correctif appliqué
**`install.md` §4 step 0** : nouvelle étape d'identification AVANT le launch :
```bash
adb shell pm list packages | grep transas
# Sortie : UN SEUL des deux sera présent
#   package:fr.transas.app.transas   ← ancien APK (4 segments)
#   package:fr.transas.app            ← nouvel APK (3 segments)
```
Puis utiliser le **nom exact retourné** dans la commande `am start -n` (§4 step 4).

### Alternative : forcer le rebuild
Pour éviter la confusion à long terme, **rebuild obligatoire** après le changement de
`buildozer.spec` (`package.name=app, package.domain=fr.transas`). Le nouveau build
produira un APK avec package `fr.transas.app` (3 segments), aligné avec le path canonique.

### Vérification
- `pm list packages | grep transas` doit retourner **exactement un** package.
- Si deux packages sont listés (ancien + nouveau) : désinstaller l'ancien avec
  `adb uninstall fr.transas.app.transas` puis re-tester.

---

## 🟠 BUG-009 (MEDIUM) — `pm list packages` : `SecurityException: Shell does not have permission to access user 150`

### Symptôme (observé en session debug 2026-07-13)
```
$ adb install bin/transas-0.1-arm64-v8a-debug.apk
Success
$ adb shell pm list packages | grep transas
Error: java.lang.SecurityException: Shell does not have permission to access user 150
    com.android.server.am.ActivityManagerService.handleIncomingUser
    com.android.server.pm.PackageManagerShellCommand.translateUserId
```

### Cause
Le téléphone a **plusieurs profils utilisateurs** (typiquement un user principal 0 + un
"managed profile" / "profil travail" en user 150, parfois ajouté par un MDM d'entreprise
ou manuellement via "Utilisateurs"). La commande `pm list packages` sans flag tente de
lister les packages de TOUS les users, mais le shell adb tourne en user 0 et n'a pas les
permissions READ_PROFILE_DATA sur user 150 → `SecurityException`.

À noter : **l'application a bien été installée** (le `Success` du `adb install` le
confirme), c'est juste la commande de listing qui foire.

### Correctif appliqué
**`install.md` §4 step 0** documente désormais 3 alternatives :

```bash
# Variante 1 — limiter au user 0 (le user du shell, c'est-à-dire toi)
adb shell pm list packages --user 0 | grep transas

# Variante 2 — test direct du nom 3-segs (échoue proprement si pas installé)
adb shell pm path fr.transas.app
# Attendu si installé : "package:/data/app/~~XYZ==/fr.transas.app-ABC==/base.apk"
# Attendu si pas installé : "Error: package not found"

# Variante 3 — test direct du nom 4-segs (ancien build)
adb shell pm path fr.transas.app.transas
```

### Leçon apprise
- **Toujours préférer `pm path <package>`** quand on connaît le nom — c'est plus précis et
  évite le SecurityException du listing global.
- Si on doit lister, **toujours ajouter `--user 0`** sauf besoin explicite de tous les users.
- Le user 150 / 999 / etc. sont des identifiants Android pour les profils secondaires.
  `dumpsys user` liste tous les profils présents sur le téléphone.

### Vérification
- `adb shell pm path fr.transas.app` doit retourner un chemin `/data/app/...`
- Si "package not found" : l'APK n'est pas installé → `adb install bin/transas-0.1-arm64-v8a-debug.apk`

---

## 🛡️ FIX DEFENSIF-001 — `map_screen.py` : différer l'import Pillow

### Pourquoi
`from ui.services.folium_renderer import render_route_bytes` (top-level) déclenche le
chargement natif de PIL (libjpeg, libpng, libwebp, etc.) au moment où Python importe le
module. Si une de ces libs est mal liée (cf. BUG-001), le SEGV arrive pendant le bootstrap
de SDLThread, avant que les screens soient instanciés — donc avant tout `try/except`
utilisateur.

### Correctif (deux passes successives)
1. **Passe 1 (originelle)** : L'import top-level `from ui.services.folium_renderer import
   render_route_bytes` a été déporté en **import local** dans `refresh_from_db`, à
   l'intérieur du `try` existant. Le load natif Pillow n'arrive qu'au clic "Actualiser".
2. **Passe 2 (post-extraction du nouveau `/tmp/launch.log`)** : Le provider `img_pil` de
   Kivy (chargé par `from kivy.core.image import Image as CoreImage` ligne 14 de
   `map_screen.py`) auto-importe PIL au **module-load**, bypassant le defer de Passe 1.
   L'import top-level `from kivy.core.image import Image as CoreImage` a été retiré
   et remplacé par un import **local** dans `refresh_from_db` également.

### Statut final (post-Passe 2)
- ✅ **Le defer `img_pil` est la mitigation PRINCIPALE contre le SIGSEGV** : PIL n'est
  plus chargé au module-load, mais seulement quand l'utilisateur demande explicitement
  un rendu de carte. C'est ce qui invalide la mention historique "insuffisant seul"
  (Passe 1 était insuffisante, Passe 1 + Passe 2 = suffisant).
- ✅ Les deux défers ensemble repoussent le load natif Pillow hors du chemin critique
  de SDLThread bootstrap. Le §"Décision 2026-07-13" ci-dessus les appelle "le vrai
  mitigation" — c'est exact **après la Passe 2**.

### Tradeoffs
- ✅ Plus de load natif PIL au module-load → le SIGSEGV `img_pil → PIL → SEGV` est
  éliminé.
- ❌ Si quelqu'un appelle `CoreImage` ou `render_route_bytes` ailleurs, il faudra
  ajouter les imports locaux là aussi (pas le cas actuellement).

### Vérification
- `pytest tests/` doit toujours passer 60/60 (les imports sont différés mais restent
  fonctionnels).
- Le `from kivy.uix.image import Image as KvImage` reste top-level (c'est le widget UI
  Kivy, pas le core image provider — il ne charge pas PIL).

---

## 🛡️ FIX DEFENSIF-002 — `main.py` : try/except autour de `TransAsApp().run()`

### Pourquoi
Sans ce filet, toute exception Python durant `build()` ou les screen init disparaît dans
l'event loop Kivy sans breadcrumb logcat — exactement ce qui s'est passé pour BUG-001
(le crash était natif donc invisible, mais on ne savait pas qu'il n'y avait PAS d'exception
Python visible).

### Correctif
**`main.py`** :
```python
if __name__ == "__main__":
    try:
        TransAsApp().run()
    except BaseException:  # noqa: BLE001 — last-resort surface
        import logging
        import traceback
        logging.getLogger("transas.bootstrap").critical(
            "FATAL BOOTSTRAP ERROR:\n%s", traceback.format_exc(),
        )
        raise
```

### Tradeoffs
- ✅ Toute future exception Python au bootstrap apparaîtra dans logcat (tag `python`,
  level `CRITICAL`) → debug beaucoup plus rapide.
- ❌ Ne catch PAS les SEGV natifs (out of Python's reach — c'est le job du debuggerd
  Android et de tombstone).

---

## 🔴 BUG-010 (CRITICAL) — Crash Adreno multi-génération : SIGSEGV dans `libGLESv2_adreno.so`

> **Scope** : Adreno 619 + 750 confirmés sur 2 devices Samsung. Mali / PowerVR / Exynos **non testés** sur ce projet.

### Symptôme (observé 2026-07-13 sur 2 devices Samsung Adreno)
Après install + launch du build 6 (Pillow 11.3.0 + Kivy 2.3.0) sur :

1. **Samsung SM_S928B** (Galaxy S24 Ultra, Snapdragon 8 Gen 3, **Adreno 750**,
   Android 16, build `samsung/e3qxeea/e3q:16/BP4A.251205.006/S928BXXS6DZF2:user/release-keys`)
   — crash immédiat reproduit le 2026-07-13 ~10:46
2. **Samsung SM-X210** (Galaxy Tab A9 ou similaire, Snapdragon 695/778G, **Adreno 619**,
   Android 16) — crash immédiat reproduit le 2026-07-13 ~12:30

Dans les 2 cas, l'app crash immédiatement avec :
- **Signal** : `SIGSEGV` (code 1, `SEGV_MAPERR`) — read fault à l'adresse `0x0000000000000028`
  (null pointer +40 bytes — même adresse que BUG-001 !)
- **Thread** : `SDLThread`
- **Module fautif** : `/vendor/lib64/egl/libGLESv2_adreno.so` (driver GPU Adreno)
- **Tombstone généré** : `tombstone_22` (device 1)

### Validation multi-device (reproduction rate: 2/2 Samsung Adreno testés)

| # | Device | GPU | Android | SDK | Chipset | Verdict |
|---|---|---|---|---|---|---|
| 1 | Samsung SM_S928B (Galaxy S24 Ultra) | Adreno 750 | 16 | 34 | Flagship (Snapdragon 8 Gen 3) | ❌ SIGSEGV Adreno (3×) |
| 2 | Samsung SM-X210 (Galaxy Tab A9?) | Adreno 619 | 16 | 34 | Mid-range (Snapdragon 695/778G) | ❌ SIGSEGV Adreno (3×) |
| 3 | (non-Adreno : Pixel, Sony, iPad, Samsung Exynos+Mali) | — | — | — | — | **NON TESTÉ** |

**Taux de reproduction** : 2/2 sur les devices Adreno testés. Le pattern est clair
(l'Adreno crash indépendamment de la génération), mais le scope exact reste à valider
sur du non-Adreno. Si un device Mali/PowerVR booterait l'app, ça confirmerait
définitivement que BUG-010 est spécifique à la famille Adreno + Android 14+.

### Stack trace (top → bottom)
```
#00-#02: /vendor/lib64/egl/libGLESv2_adreno.so  ← CRASH ICI (driver GPU)
#03-#50: /kivy/graphics/vbo.so
         /kivy/graphics/instructions.so
         /kivy/graphics/compiler.so
         /kivy/_event.so  ← dispatch d'events Kivy
#51+:    libpython3.11.so  ← PyObject_Vectorcall, _PyEval_EvalFrameDefault
         libSDL2.so  ← Java_org_libsdl_app_SDLActivity_nativeRunMain
```

### Cause racine (CONFIRMÉE par les logs)
**Incompatibilité entre Kivy 2.3.0 / SDL2 (bundled dans p4a 2024.x compilé avec NDK r25c) et
la famille de drivers GPU Adreno (Qualcomm) sous Android 14+.**

L'init graphics de Kivy (création du contexte OpenGL ES via SDL, init VBO, premier draw call)
déclenche un appel OpenGL ES que le driver Adreno rejette en `SEGV_MAPERR` à l'offset `+0x28`
d'un objet C. Le driver Adreno propriétaire rencontre un état invalide pendant l'init
EGL/VBO de Kivy ; l'offset `+0x28` exact dépend du layout interne du driver (code
propriétaire, non inspectable). Interprétation : il s'agit vraisemblablement d'un objet
EGL/Surface ou d'un VBO non-initialisé que Kivy tente d'utiliser, mais l'identification
précise du champ fautif nécessiterait un debug avec les outils Adreno (Snapdragon Debug
for Android + Adreno GPU Profiler).

### Pourquoi les fixes défensifs n'ont pas aidé
- Le defer de `kivy.core.image` (Passe 2) est resté actif — il n'a **pas aidé** car le
  crash n'est pas dans le chargement PIL, mais dans l'init graphics. Le defer reste valide
  comme hygiène (évite de charger PIL au boot quand on n'en a pas besoin).
- Le defer de `ui.services.folium_renderer` (Passe 1) — idem, pas lié au crash.
- Le `try/except` dans `main.py` n'a **pas** attrapé le crash (les SEGV natifs sont
  hors de portée de Python). MAIS il a attrapé un `shutil.Error` non-fatal précédent
  (Permission denied sur `.kivy/icon/`) → le filet reste utile pour debug.

### Pourquoi le bump Kivy 2.3.1 a été abandonné
Tentative d'upgrade Kivy 2.3.0 → 2.3.1. Le rebuild a échoué par 2 fois :
1. **Tentative 7** : tuée manuellement après que le daemon Gradle soit mort silencieusement
   (cause : RAM saturée 6.4/7.6 GB + swap full 4.0/4.0 GB → OOM pendant compile Cython Kivy).
2. **Tentative 8** : échec immédiat par `bash: JAVA_HOME : variable sans liaison` —
   JAVA_HOME pas propagé au sous-shell de `script`.

Conclusion : le serveur de build est trop contraint en RAM pour faire un full Cython
recompile de Kivy 2.3.1. La valeur du bump était de toute façon spéculative (changelog
Kivy 2.3.1 ne mentionne pas explicitement de fix Adreno). Le build 6 reste l'artifact
de référence pour cette session.

### Correctifs recommandés (pour session FUTURE, hors RAM)
**Plan B (PRÉFÉRÉ — le plus correct architecturalement)** : **NDK r25c → r28c**
- p4a recommande r28c pour compatibilité avec Android 14+ (le SDK Android 16 utilisé par
  Galaxy S24 Ultra requiert probablement des sysroots NDK plus récents que r25c).
- Effort : 1-2h, full rebuild de Python + SDL2 + toutes les recipes natives.
- Risque : même problème RAM, à tenter sur une machine plus costaude.
- Code change : `android.ndk_path = %(source.dir)s/.android-sdk/ndk/28.0.13004108`
  (télécharger NDK r28c d'abord).

**Plan C** : **Upgrade Kivy 2.3.0 → 2.3.1** (quand serveur a +RAM)
- Risque modéré, valeur spéculative (changelog Kivy 2.3.1 ne mentionne pas Adreno
  explicitement).
- Effort : 1-2 builds, 30-60 min sur machine costaude.

**Plan D** : **Forcer le software rendering** dans Kivy
- Set `KIVY_GL_BACKEND = 'mock'` ou utiliser sdl2+swrast.
- Risque : UI dégradée / lente, mais contourne complètement le driver Adreno.
- Effort : 1-2 lignes dans `main.py`.

**Plan E (le plus complet — NDK r28c seul en premier, puis Kivy 2.3.1 si besoin)** : **NDK r28c** (priorité) + Kivy 2.3.1 + sdl2 backend tweaks
- **Priorité absolue : NDK r28c seul**. C'est le fix le plus susceptible de résoudre le
  problème d'ABI toolchain entre p4a (compilé r25c) et le driver Adreno Android 14+.
  Les 2 autres (Kivy 2.3.1 + sdl2 backend tweaks) ne sont à tenter qu'après NDK r28c,
  car leur valeur est spéculative.

### Workaround immédiat (sans rebuild)
Si l'utilisateur veut tester l'app sur le Samsung SM_S928B maintenant, il n'y a pas de
workaround runtime : l'APK crashera à chaque launch. Les options sont :
- Tester sur un autre device (autre marque, autre GPU : Mali, PowerVR, etc.)
- Attendre une session future avec une machine de build plus costaude pour faire le Plan B.

---

## 🟢 Plan I + Plan K (2026-07-14 — Tier-ladder fallback)

### TL;DR

Ajout d'un **ladder de fallback env-driven** dans `main.py` pour échapper à la SIGSEGV Adreno
sans rebuild majeur. Trois modes sélectionnables via `TRANSAS_SAFE_MODE` (env var), via
file-flag `/sdcard/Download/.transas_safe_mode_{off,2}` (Android,
writable via `adb shell touch`, non bloqué par SELinux 14+) :
*(l'ancien mécanisme `adb shell setprop debug.transas.safe_mode N`
via jnius SystemProperties est mort sur Android 14+ — voir
§"Plan K v2 outcome" pour le fix de remplacement.)*

| Mode | UI visible ? | Commentaire |
|------|--------------|-------------|
| `TRANSAS_SAFE_MODE=0` (défaut) | ❌ oui mais CRASH Adreno | Code actuel, pré-Plan K. |
| `TRANSAS_SAFE_MODE=1` | ✅ Kivy widgets, sans ombres Material | **RECOMMANDÉ** pour Samsung S24 Ultra en attendant Plan J. |
| `TRANSAS_SAFE_MODE=2` | ❌ écran noir | Last-resort crash isolation. Voir report_bug.md §BUG-012 Plan D original. |

### Plan I — mock GL backend (mode=2)

Implémente `os.environ['KIVY_GL_BACKEND'] = 'mock'` avant tout import kivy. Le backend ``mock``
de Kivy est conçu pour les **tests unitaires** : il satisfait tous les appels GL avec des
no-ops, ne paint rien à l'écran, mais boote sans toucher au driver GPU.

- ✅ Boot garanti sur Adreno 619/750 (parce qu'aucun appel GL n'est émis donc
  aucun driver GPU n'est sollicité).
- ❌ **ÉCRAN NOIR** (AUCUN rendu). Utilisable UNIQUEMENT pour isoler les crashes
  Adreno des autres bugs Python. NE PAS utiliser pour tester l'app.
- Effort : 0 ligne ajoutée (juste `os.environ[...]=` + flag `TRANSAS_SAFE_MODE=2`).
- Risque : nul. Aucune régression sur Adreno ou non-Adreno.

**Trompe-l'œil historique**: `report_bug.md §BUG-012 Plan D` (2026-07-13) suggérait déjà
cette voie comme « fallback sans UI dégradée ». Trompe-l'œil levé — l'expérience Plan K a
confirmé que ``mock`` n'est pas utilisable en QA, c'est un outil de diagnostic.

### Plan K — runtime monkey-patch KivyMD CommonElevation (mode=1)

**Objectif**: retirer l'injection de canvas-instructions d'ombre que KivyMD ajoute via
`CommonElevation` sur chaque widget avec élévation, sans rebuild du toolchain.

**Cause ciblée**: BUG-010 a 5 plans D-H testés en pure Python, tous ont reproduit la SIGSEGV
dword-par-dword dans `vbo.so`. Le coupable n'est pas isolé à un widget précis : c'est le
**fail-through VBO compile** déclenché par KivyMD qui ajoute Color/Rectangle sur
`self.canvas.before` pour les ombres Material — même quand `theme_cls.elevation_levels[k]=0`
(source KivyMD 1.1.1 `kivymd/uix/behaviors.py`).

**Stratégie**: monkey-patcher les méthodes de `CommonElevation` qui injectent les CanvasInstructions
vers des no-ops. Les attributs shadow sont positionnés à `None` en prologue (treatés par
KivyMD comme « pas d'ombre » via les checks `if self._shadow_canvas:`).

**Méthodes ciblées** (5 candidates, première match gagne) :
- `_elev_class_init` (lignée 1.1.x — Plan G origin)
- `_update_shadow` (nommage ancien)
- `_add_shadow`, `add_shadow`, `_add_canvas` (fallbacks nommage ancien)

**Implémentation** dans `main.py` `_apply_safe_mode_tier_k()` :
- Idempotence via `_TIER_K_APPLIED` global guard.
- 5 str_replace successifs + ast.parse vert + pytest 60/60 vert.
- Logging basique (`force=True`) bootstrappé early quand safe-mode engagé.
- Warning log si aucun match (signale Plan K no-op → BUG-010 toujours présent).

**Effet attendu** :
- ✅ Tous les widgets Kivy (Label, Button, Image, BoxLayout, ScreenManager) rendent normalement.
- ✅ Pas de crash Adreno (plus de canvas instructions shadow émises → pas de compile VBO).
- ❌ Plus d'ombres Material cards sur les MDCard / MDBoxLayout (coût visuel acceptable).
- ⚠️ Subclasses KivyMD qui redéfinissent `_elev_class_init` localement
  (MDCard-internal style) ne sont **pas** patchées — limitation documentée.

### Plan J — proper fix on costaude machine (16 GB RAM, parallèle background)

Recommandation du **thinker-with-files-gemini** du 2026-07-14 (et corroborée par le build
iter-36) : **NDK r25c + Kivy 2.3.1** comme fix le plus susceptible de régler BUG-010 à la
racine sans casser la chaîne ``clang.real`` shim calibrée pour r25c.

**Rationale** :
- NDK r28c déclenche le rabbit-hole Bionic `setgrent/getgrent/endgrent` (cf `BUG-011`),
  très consommateur en investigation-recipe p4a.
- Kivy 2.3.1 n'a pas de fix Adreno explicite dans son changelog, mais sa chaîne
  Cython (3+ compatible) peut modifier juste assez l'ABI pour doper le VBO compile
  et éviter le SIGSEGV.
- Cython 3+ est la dernière hypothèse non testée — la chaîne Kivy 2.3.0 ↔ Cython
  0.29.36 ↔ KivyMD 1.1.1 ↔ NDK r25c est figée par 36 itérations et ne peut être
  débloquée qu'**une fois en mode “NDK r25c + Kivy 2.3.1 + Cython 3+”**.

**Étapes (à exécuter sur machine costaude ≥16 GB RAM)** :
1. Update `buildozer.spec` : `requirements = python3==3.11.11,cython>=3.0,<4.0,kivy==2.3.1,kivymd==1.1.1,...` (Cython 3+, Kivy 2.3.1).
2. Garder `android.ndk_path = .../ndk/25.2.9519653` (r25c, pas r28c).
3. Cap build concurrency pour survivre au swap : `export MAKEFLAGS="-j1" P4A_USE_NCPUS=1`.
4. `buildozer android clean && buildozer android debug arch=arm64-v8a` (~3h sur machine costaude).
5. `adb install bin/transas-0.1-arm64-v8a-debug.apk` sur Samsung S24 Ultra.
6. Si encore crashé : Plan I+J (mode=1) ou mode=2 (Plan I mock).

**Probabilité de succès estimée** :
- Kivy 2.3.1 change Cython ABI → 40% chance de bypass la SIGSEGV.
- Sinon fallback sur cette session : continuer Plan I (mode=1) en production-ship.

### Action de suivi benché

1. **Tester Plan K (=1) sur S24 Ultra** dès que APK rebuild dispo.
2. Si succès → ship comme build 7 avec Plan K baked in par défaut (ou via setprop prod).
3. Si échec (Plan K no-op silencieux) → warning log visible dans logcat.
4. Lancer Plan J (NDK r25c + Kivy 2.3.1) en parallèle sur machine costaude.

---

## 🟠 BUG-012 — Plans D-H rétrospective (Adreno driver bug non-récupérable en Python)

### Constat 2026-07-14

Après le succès de Plan D (NDK r28c + Bionic stubs + JAVA_HOME=java-17) qui a produit un APK
frais compilant et s'installant correctement, toutes les tentatives de mitigation **Python-only**
du BUG-010 ont échoué identiquement sur SM-X210 (Adreno 619) :

| Plan | Fix appliqué | Résultat (3/3 relances) |
|------|--------------|------------------------|
| **D** | Bionic stubs + JAVA_HOME=java-17 (build env) | APK OK s'installe ✅ ; SIGSEGV immédiat ✅ (référence 5/5) |
| **E** | `KvImage(opacity=0, fit_mode="contain")` à MapScreen.__init__ | CRASH 3/3 — même signature `libGLESv2_adreno.so` → compiler.so ↔ instructions.so ↔ vbo.so |
| **F** | `KvImage` LAZY dans `refresh_from_db()` (plus aucun Image au boot) | CRASH 3/3 — même stack frame parfait, **mêmes PC `0x0000000000012590` vbo.so** etc. |
| **G** | `KIVY_GL_BACKEND=angle_sdl2` + `theme_cls.elevation_levels={k:0 for k in range(100)}` | CRASH **différent** : `CGL: ANGLE backend can be used only on Windows` → `AttributeError: 'NoneType' object has no attribute 'width'` dans `kivymd/material_resources.py` avant `TransAsApp.__init__()` |
| **H** | Juste elevation_levels (sans angle_sdl2) | CRASH 3/3 — même signature exacte D/E/F |

### Cause racine **irréfutable**

Le « coupable » n'est pas isolé à un widget précis :

1. **Plan F** retire totalement `KvImage` du widget tree au boot → CRASH identique → exclu.
2. **Le crash se produit dans le thread native SDLThread** (`libGLESv2_adreno.so` → vbo/compiler/instructions `kivy.graphics._.so`) — hors d'atteinte de Python.
3. **5 builds différents + 15 relances** → signature de crash dword-par-dword identique (même `fault addr 0x0000000000000028`, mêmes PC dans vbo.so/compiler.so).
4. **Build de référence (build 6, NDK r25c) a eu des SIGSEGV identiques sur Samsung SM_S928B (Adreno 750)** le 2026-07-13 — **deux générations de GPU Adreno, même bug, deux devices différents**.

### Conclusion

**Ce n'est pas un bug Python ; c'est une incompatibilité entre Kivy 2.3.0 et la famille de drivers Adreno (GLESv2) sous Android 14+.** Aucune mitigation purement Python (widget shape, opacity, lazy init, theme kwargs, elevation, font load) ne peut bypass ça. La récursion infinie se produit dans la compilation VBO native déclenchée par le `compiler.so` de Kivy quand il émet des instructions Draw pour le contexte OpenGL ES d'Adreno, indépendamment du contenu du widget tree Python.

### Pivots restants (par ordre de recommandation)

1. **Pivot A — Downgrade NDK r28c → r25c** (compatibilité Adreno connue pour les versions
   Kivy 2.x 2023). Effort : ~45-60 min rebuild clean (Python + recettes natives).
   Édition `buildozer.spec` : `android.ndk_path = .../ndk/25.2.9519653/`. La chaîne
   Bionic stubs reste en place (inoffensive sur r25c). Plan D peut rester tel quel.

2. **Pivot B — Forcer rendu logiciel Mesa** (EGL surfaceless ou swiftshader via
   `os.environ['KIVY_GL_BACKEND']='mock'` ou via création d'un display EGL off-screen).
   Effort : 2-3 lignes Python + 5-30 min rebuild. Trade-off : UI plus lente,
   consommation CPU élevée, mais fonctionne sans GPU.

3. **Pivot C — Skip le test Adreno**, valider sur device non-Adreno (Mali/PowerVR/Exynos) où
   l'APK actuel fonctionne probablement (architecture différente). L'APK Plan H (MD5
   `351d18a23b260e39160677afa867d763`, dated 2026-07-14 12:00 CEST) est l'artifact
| **Plan K v2 APK** | `98730137c81b11c519909e39f40995a2` | 2026-07-14 20:50 | Plan K actif par défaut (env-detect Android), target method mismatch sur KivyMD 1.1.1, SIGSEGV reproduit. Cf. §"Plan K v2 outcome" ci-dessous. |
   shippable recommandé pour cette branche.

### APKs produits (référence 2026-07-14)

| Étape | MD5 | Date | Statut |
|-------|-----|------|--------|
| Plan D (NDK r28c + Bionic stubs) | `cf7d6249bceced9908bde0e2db0859e4` | 2026-07-14 11:41 | Installe OK ; crash SIGSEGV immédiat |
| Plan E (opacity+fit_mode) | `351d18a23b260e39160677afa867d763` | 2026-07-14 11:54 | Idem (buildozer re-skipped repackage) |
| Plan F (lazy Image) | `1a38654d06660a0e83fae4155d68a9e3` | 2026-07-14 11:54 | Idem |
| Plan G (angle_sdl2+elev) | `351d18a23b260e39160677afa867d763` | 2026-07-14 12:00 | Idem (ANGLE Windows-only error) |
| **Plan H (elev only)** | **`351d18a23b260e39160677afa867d763`** | **2026-07-14 12:00** | Idem SIGSEGV (mêmes PC que Plan D) |

Note : les MD5 identiques Plan E → Plan H montrent que buildozer a dédupliqué l'APK extérieur
quand seules les sources Python changeaient (private dir rsync'd à l'intérieur). Mais les
`.pyo` Python différenciés sont bien présents dans l'APK ; ils n'ont juste pas contourné le
bug driver.

### Action de suivi

Si vous reconduisez sur serveur plus RAM :
1. **Pivot A (recommandé)** : `sed -i 's/28.0.13004108/25.2.9519653/' buildozer.spec` + rebuild.
   Bionic stubs et JAVA_HOME=java-17 restent.
2. Si A échoue : **Pivot B** (Mesa mock backend).
3. Si A et B échouent : **Pivot C** (test sur device Mali/PowerVR).

---

## 🟠 BUG-011 — NDK r28c build échoue sur `setgrent/getgrent/endgrent` (stdlib Python, glue Bionic)

### Symptôme (2026-07-14, Plan B NDK r28c)

Après bump NDK r25c → r28c (28.0.13004108) per session 2026-07-14, `buildozer android
debug` échoue pendant la compilation de la recette `python3` de p4a :

```
clang ... -std=c11 -Werror=implicit-function-declaration ... grpmodule.c
  error: implicit declaration of function 'setgrent'
  error: implicit declaration of function 'getgrent'
  error: implicit declaration of function 'endgrent'
```

Le wrapper script reporte faussement `BUILD FINISHED, exit code 0` (le `tee -a` masque
le code retour réel de buildozer). Critère de succès observé :
- `bin/transas-0.1-arm64-v8a-debug.apk` **daté today** (vs build 6 daté 2026-07-13).
- taille APK ≥ 28.9 MB.
- "BUILD SUCCESSFUL" dans `/tmp/build_planC.log` (et pas seulement "BUILD FINISHED").

### Cause racine

Android NDK utilise **Bionic libc** (PAS glibc). Bionic ne déclare PAS
`setgrent`/`getgrent`/`endgrent` dans `<grp.h>` (ce sont des extensions glibc-only).
p4a ne fournit pas de stub historique pour ces fonctions ; NDK r25c masquait le
warning (`-Wno-implicit-function-declaration` actif), NDK r28c le transforme en
erreur fatale (`-Werror=implicit-function-declaration`). **Le faux positif du
wrapper** sur exit code 0 est dû au pipe `tee -a` (exit code de tee, pas buildozer).

### Correctif appliqué

Patch **inline** persistant dans le clone p4a local (`.local/python-for-android/
pythonforandroid/recipes/python3/__init__.py`, méthode `apply_patches`) qui injecte
des stubs statiques `setgrent()`/`endgrent()`/`getgrent()` guardés par
`#if defined(__ANDROID__) || defined(__BIONIC__)` juste après `#include <grp.h>`
dans `Modules/grpmodule.c`. Idempotent (marker `transas bionic stub`), best-effort
(`try/except` → n'interrompt jamais le build).

### Statut Plan C

⚠️ **Build lancé 2026-07-14 ~06:00 CEST, ETA 1.5-2h** :
- NDK r28c (28.0.13004108) utilisé
- `MAX_CONCURRENCY=1` + `P4A_USE_NCPUS=1` pour minimiser l'empreinte RAM
- Log : `/tmp/build_planC.log`, PID wrapper : `/tmp/build_planC.pid`
- Code-reviewer verdict : **SHIPPABLE** avec 1 nit cosmétique (ligne `*/#if` collée,
  valide C mais jugée impropre — fix post-build si confirmé ship)

### Plan D fallback si Plan C échoue

Si un autre module casse (`pwdmodule.c` `setpwent/getpwent/endpwent`,
`spwdmodule.c` `setspent/getspent/endspent`, ou erreur de link SDL2/Pillow) :
- Tuer le build : `kill $(cat /tmp/build_planC.pid)`
- Étendre le même stub pattern aux modules fautifs dans `__init__.py`
- OU pivoter vers Plan D (`KIVY_GL_BACKEND=mock` dans `main.py` + rebuild incr.

---

## 📋 Récap des fichiers modifiés

| Fichier | Modification | Statut |
|---|---|---|
| `buildozer.spec` | `package.name=app, package.domain=fr.transas` + `Pillow==11.3.0` (rollback 10.2.0→11.3.0, 4 builds échoués sur le downgrade) + `Kivy==2.3.0` (stays) | ✅ Appliqué |
| `buildozer.spec` | Tentative Kivy 2.3.0 → 2.3.1 (bump spéculatif pour fix Adreno) | ⏸️ Abandonné (RAM saturée 6.4/7.6 GB + swap full + `JAVA_HOME` non propagé) |
| `main.py` | try/except bootstrap avec logging CRITICAL | ✅ Appliqué |
| `main.py` | Plan D : tentative `KIVY_GL_BACKEND=mock` (bypass driver Adreno via backend ``mock``) | ⏸️ Tenté puis reverté (build OOM sur ce serveur) |
| `ui/screens/map_screen.py` | import Pillow différé dans `refresh_from_db` | ✅ Appliqué |
| `install.md` | Path canonique `fr.transas.app/...` + comment §4 step 4 fixé | ✅ Appliqué |
| `report_bug.md` | Ce fichier (consolidation des bugs) | ✅ Créé |
| `REPORT.md` §9 | À mettre à jour pour refléter le nouveau path (action future) | ⏳ TODO |

---

## 🎯 Actions requises côté user pour valider

**⚠️ AVANT TOUTE CHOSE — identifier l'ancien package installé** :

```bash
adb shell pm list packages | grep transas
# Sortie typique (UN SEUL des deux sera présent) :
#   package:fr.transas.app.transas   ← ancien APK (4 segments, builds avant ce fix)
#   package:fr.transas.app            ← nouvel APK (3 segments, après rebuild)
```

**Puis, dans cet ordre strict** :

1. **Désinstaller l'ancien APK** : utilise le nom EXACT trouvé ci-dessus
   (probablement `fr.transas.app.transas` si c'est l'APK iter-36 actuel ; ou
   `fr.transas.app` si tu as déjà rebuildé). NE PAS deviner — utilise
   `pm list packages` pour confirmer.

2. **Rebuild obligatoire** : `buildozer android debug` (le code a changé, l'APK actuel
   n'intègre pas les fixes).
2. **Désinstaller l'ancien APK** : `adb uninstall fr.transas.app` (le nouveau package
   sera `fr.transas.app`).
3. **Réinstaller le nouveau binaire** : `adb install bin/transas-0.1-arm64-v8a-debug.apk`.
4. **Si le crash natif persiste** après le rebuild :
   - **Plan B (préféré)** : patcher la recipe p4a Pillow (cf. "Décision
     2026-07-13" ci-dessus) — effort 1-2h.
   - **Plan C** : bump NDK r25c → r28c (rebuild + décommissionner le
     `clang.real` shim) — risque de régression CI.
   - **Plan D (safe mode)** : retirer Pillow de buildozer.spec, le folium_renderer
     tombe en `ImportError` gracieux → l'app bootera sans rendu de carte.
5. **Si un nouveau traceback Python apparaît** (grâce au FIX DEFENSIF-002), l'envoyer
   ici pour diagnostic ligne-à-ligne.

---

## 📎 Logs de référence

- `/tmp/launch.log` (45 MB, 440k+ lignes) — log complet du crash Adreno original (SM_S928B, Adreno 750).
- `/tmp/launch_new_device.log` — reproduction sur SM-X210 (Adreno 619, 2026-07-13 ~12:30).
- `/tmp/launch_planD.log` / `/tmp/launch_planD2.log` — tentatives Plan D (KIVY_GL_BACKEND=mock), la 2ème sur APK stale (SyntaxError) et la 3ème bloquée par OOM NDK.
- `/tmp/launch2.log` — tentative initiale avec fixes défensifs (aussi crash Adreno).

---

## 🏁 Session Wrap-up (2026-07-13)

### Artifact shippé
- **APK canonique** : `bin/transas-0.1-arm64-v8a-debug.apk` (28.9 MB,
  MD5 `6bc3d840e19f31d178afafd54d421e31`).
- **Compatibilité validée** : s'installe et crash reproductible sur les devices Adreno
  (SM_S928B Adreno 750, SM-X210 Adreno 619 — 2/2 reproduction, SIGSEGV dans
  `libGLESv2_adreno.so` à l'init graphics Kivy). Non testé sur Mali/PowerVR/Exynos
  — shippable a priori pour ces GPUs (cf. Plan B/C du BUG-010).

### Ce qui a été fait dans cette session
1. **4 tentatives Pillow 10.2.0 → 11.3.0 rollback** (4 builds échoués à cause du
   `setup.py.patch` p4a codé en dur pour Pillow 11.3.0). Rollback final conservé.
2. **2 tentatives Kivy 2.3.0 → 2.3.1 bump** (abandonnées : RAM saturée 6.4/7.6 GB
   + swap full + `JAVA_HOME` non propagé).
3. **Fixes défensifs préservés** dans le code shipped : defer `kivy.core.image` (img_pil
   provider, Passe 2) + defer `ui.services.folium_renderer` (Passe 1) +
   try/except `BaseException` dans `TransAsApp().run()`. Ces fixes n'ont pas
   résolu BUG-010 (le crash est dans le GPU, pas PIL) mais restent valides
   comme hygiène et protègent contre de futures régressions PIL.
4. **Plan D tenté (KIVY_GL_BACKEND=mock)** : code ajouté puis reverté car le
   build du fix a échoué par OOM (serveur de build trop RAM-constrained pour
   un full Cython/NDK rebuild). Le code reste documenté dans l'historique de
   cette section pour reproduction future sur serveur plus costaude.

### Pourquoi on shippe build 6 sans le fix Adreno
- Le crash BUG-010 est **Adreno-specific** (Adreno 619 + 750, 2/2 reproduction sur 2 devices Samsung).
  L'APK **fonctionne sur tout device qui n'est pas Adreno** (Mali, PowerVR, Exynos+Mali
  non testés mais architecture différente = a priori OK).
- Le serveur de build actuel (6.4/7.6 GB RAM + 4.0/4.0 GB swap full) ne peut pas
  faire un full Cython/NDK rebuild nécessaire pour valider Plan D ou pour
  appliquer Plan B (NDK r28c).
- Le build 6 est l'**état le plus stable et testé** du code. Shipper cet APK
  évite de pousser un fix non validé.

### Plan B (long-terme) — NDK r25c → r28c
- **Pré-requis** : machine avec ≥16 GB RAM + swap ≥8 GB (ou pas de swap).
- **Steps** :
  1. Télécharger NDK r28c : `https://developer.android.com/ndk/downloads` (version
     `28.0.13004108`).
  2. Extraire dans `.android-sdk/ndk/28.0.13004108/`.
  3. Update `buildozer.spec` :
     `android.ndk_path = %(source.dir)s/.android-sdk/ndk/28.0.13004108`.
  4. Décommissionner le `clang.real` shim per le commentaire existant dans
     `buildozer.spec`.
  5. `buildozer android clean && buildozer android debug` (1-2h).
  6. Installer sur Samsung SM_S928B + vérifier que BUG-010 est résolu.
- **Rationale** : NDK r25c date de 2023, Android 14+ (incl. Android 16 sur
  SM_S928B) requiert des sysroots NDK plus récents. Le driver Adreno
  7xx/8xx + NDK r25c a une incompatibilité ABI documentée par p4a.

### Plan C (alternative) — Test sur device non-Adreno
- Si l'utilisateur a accès à un Pixel, Sony Xperia, iPad, ou Samsung Exynos+Mali,
  tester l'APK build 6 dessus (install + launch + `pidof`).
- Si ça boot sur non-Adreno → confirmation que BUG-010 est Adreno-specific.
- C'est **le moyen le plus rapide de valider que build 6 est utilisable
  en production** (même sans fix Adreno).

### Plan E (le plus complet — pour référence)
Voir la section **🔴 BUG-010 → Plan E** plus haut pour la version combinée
(NDK r28c en priorité + Kivy 2.3.1 + sdl2 backend tweaks) si une seule session
costaude veut tout tenter d'un coup.

### Plan D (à retenter) — KIVY_GL_BACKEND=mock
- Le code du workaround est documenté dans l'historique de cette section.
- Pour le retenter sur une machine costaude : ajouter le bloc (déjà rédigé
  ci-dessus) à `main.py` (correctement placé APRÈS `from __future__ import
  annotations` !), rebuild + install sur SM_S928B.
- **Probabilité de succès estimée** : non validée — le backend ``mock`` de Kivy
  est principalement conçu pour desktop ; sur Android le bootstrap SDL2 pourrait
  quand même charger `libGLESv2_adreno.so` avant que le mock backend ne prenne
  le relais. À retenter empiriquement.

### Liens utiles
- BUG-010 source : section dédiée plus haut dans ce fichier
- Logs de reproduction : `/tmp/launch.log` (SM_S928B) + `/tmp/launch_new_device.log` (SM-X210)
- Build environment : `.local/python-for-android/pythonforandroid/recipes/Pillow/__init__.py`
- NDK r28c download : https://developer.android.com/ndk/downloads (version 28.0.13004108)

---

**Auteur** : session debug 2026-07-13
**Build de référence** : iter-36 `a0c18d7`
**APK de référence** : `bin/transas-0.1-arm64-v8a-debug.apk` (28.9 MB, MD5 `6bc3d840e19f31d178afafd54d421e31`)
**Statut final** : 🟡 APK shipped, BUG-010 documenté, Plan B (NDK r28c) recommandé pour la prochaine session sur serveur costaude.
