# Procédure de release TransAs v0.1 — Path A (sideload)

Ce document décrit, dans l'ordre exact, **les 4 commandes restantes** pour
qu'un APK signé soit disponible en téléchargement sur GitHub Releases et
que le repo passe en privé. Tout est déjà en place côté code :

- ✅ Étape 1+2 (core + database) — 46 tests verts
- ✅ Étape 3 (UI Kivy/KivyMD) — 14 tests verts
- ✅ `buildozer.spec` (avec Pillow)
- ✅ `.github/workflows/release.yml` (build APK signé sur tag `v*` ; deps résolues en Python 3.11, SDK/NDK remplacés par ceux du runner avant `buildozer`)
- ✅ `.github/workflows/security.yml` (audit pip-audit + bandit + shellcheck + gitleks)
- ✅ `scripts/setup_keystore.sh` + `scripts/sign_release.sh`
- ✅ `SECURITY.md` + `requirements-audit.txt` + `.bandit`
- ✅ Code poussé sur `main` (6702 insertions, 50 fichiers)
- 🟡 **À faire : keystore + 4 secrets + tag + flip privé**

---

## 1. Générer le keystore release stable (~2 min)

```bash
cd /home/el-hadj-ousmane/Bureau/trans_as
bash scripts/setup_keystore.sh
```

Le script demande :

| Prompt | Valeur suggérée |
|--------|-----------------|
| Enter keystore password: | un mot de passe fort (≥ 16 chars, unique, stocké dans Bitwarden/KeePassXC) |
| Re-enter password: | idem |
| What is your first and last name? | `TransAs Release` |
| What is your organizational unit? | `Couriers France` |
| What is your organization? | `TransAs` |
| What is your City or Locality? | `Paris` |
| What is your State or Province? | `IDF` |
| What is the two-letter country code? | `FR` |
| Is CN=… correct? | `yes` |
| Enter key password: | (RETURN — utilise le même mot de passe que le keystore) |

Produit :

```
transas-release.jks          ← LE FICHIER À NE JAMAIS COMMITTER
scripts/last-keystore-info.txt   ← mémo local (déjà gitignoré)
```

Vérification que le keystore est OK :

```bash
keytool -list -v -keystore transas-release.jks | head -20
# doit afficher : Alias name: transas, Owner: CN=TransAs Release, …
```

---

## 2. Encoder le keystore en base64 + préparer les 4 secrets

```bash
# 2a. base64 monolinne (sans \n)
base64 -w0 transas-release.jks > transas-release.jks.b64
wc -c transas-release.jks.b64  # ≈ 4× la taille du .jks (~5 KB)

# 2b. relevez les valeurs des 4 secrets dans un coin :
echo "KEYSTORE_BASE64   = $(cat transas-release.jks.b64)"
echo "KEYSTORE_PASSWORD = <le mot de passe tapé à l'étape 1>"
echo "KEY_ALIAS         = transas                                # ou ton alias custom si tu en as choisi un"
echo "KEY_PASSWORD      = <key password tapé à l'étape 1 — souvent = KEYSTORE_PASSWORD>"
```

⚠ **Une fois les 4 secrets recopiés dans GitHub, supprime localement le `.b64`** (il contient la version encodée de ton keystore) :

```bash
shred -u transas-release.jks.b64   # ou rm -f sur SSD
```

---

## 3. Renseigner les 4 secrets sur GitHub

Va sur **https://github.com/El-hadj10/TransAs/settings/secrets/actions** :

- Clique **New repository secret** × 4 fois.
- Saisis exactement les noms suivants (la casse et le `_` comptent) :

| Name                | Secret value                                  |
|---------------------|-----------------------------------------------|
| `KEYSTORE_BASE64`   | la sortie de `cat transas-release.jks.b64`    |
| `KEYSTORE_PASSWORD` | le mot de passe keystore                      |
| `KEY_ALIAS`         | `transas` (ou ton alias)                      |
| `KEY_PASSWORD`      | le mot de passe clé                           |

- Valide chaque secret. Tu dois voir 4 secrets dans la liste.

---

## 4. Premier tag → déclenche le build APK

```bash
cd /home/el-hadj-ousmane/Bureau/trans_as
git tag v0.1
git push --tags
```

Ouvre l'onglet **Actions** sur GitHub : `release.yml` se déclenche sur le
push du tag.Le job dure **1 à 3 heures** (premier build NDK 28.0.13004108, sans cache). Trois APK seront uploadés dans
**https://github.com/El-hadj10/TransAs/releases/tag/v0.1** :

```
transas-0.1-armeabi-v7a-debug.apk   ← vieux Android 7 et avant (Redmi, Wiko)
transas-0.1-arm64-v8a-debug.apk     ← la plupart des Android depuis 2018 ⭐
transas-0.1-x86_64-debug.apk        ← émulateurs / Chromebook Linux
```

Pendant le build, la CI exécute aussi `apksigner verify -v` sur chaque APK —
si la signature échoue, le job s'arrête et tu reçois un email. Si tout
est vert, les 3 APK sont téléchargeables directement.

---

## 5. Rendre le repo privé

Va sur **https://github.com/El-hadj10/TransAs/settings** :
- Descend jusqu'à **Danger Zone**
- Clique **Change visibility** → **Make private**
- Tape le nom du repo (`El-hadj10/TransAs`) pour confirmer
- Valide

Alternative en ligne de commande (si tu as `gh` CLI authentifié) :

```bash
gh repo edit El-hadj10/TransAs --visibility private --accept-visibility-change-consequences
```

> 🔒 **Conséquence** : seul toi (et les futurs collaborateurs que tu invites)
> verront le code, les issues, et les APK signés. F-Droid et IzzyOnDroid
> exigeront un repo public — passer en privé aujourd'hui verrouille la
> distribution à GitHub Releases + sideload direct.

---

## 6. Vérification finale

Une fois le build terminé (~1-3 h après le tag) :

1. Ouvre **https://github.com/El-hadj10/TransAs/releases/tag/v0.1**
2. Tu dois voir 3 APK signés attachés à la release.
3. Télécharge `transas-0.1-arm64-v8a-debug.apk` (~30 MB).
4. Sur ton téléphone Android : active « Sources inconnues » pour ton
   navigateur (Réglages → Apps → ton navigateur → Installer apps
   inconnues → Autoriser).
5. Ouvre le `.apk` téléchargé → « Installer » → l'app apparaît dans le
   launcher sous le nom **TransAs** avec l'icône orange.
6. Premier lancement : tu arrives sur l'écran **Import** (formulaire
   adresse). Ajoute un colis, clique **+ Ajouter** puis
   **Optimiser la tournée** — la carte s'affiche sur l'écran **Map**
   avec marqueurs numérotés + polyline.

---

## 7. En cas d'erreur (debug fréquent)

| Erreur CI | Cause probable | Fix |
|-----------|----------------|-----|
| `Decode release keystore from secret` fails | mauvais base64 ou fichier tronqué | refais `base64 -w0 transas-release.jks`, ne copie pas le `+` final |
| `JAVA_HOME is not set` | le job essaye d'utiliser Temurin | normale, on bascule déjà via `actions/setup-java@v4` — vérifie que la PR a été mergée |
| `apkanalyzer: command not found` | SDK build-tools 34.0.0 manquant | le job télécharge normalement, vérifie qu'il n'y a pas eu d'erreur réseau |
| `Build failed: ndk … not found` | `android.ndk_path` ne correspond pas au NDK installé | `buildozer.spec` épingle `28.0.13004108` ; `release.yml` réécrit `android.ndk_path` vers `$ANDROIDNDK` du runner |
| `build-tools folder not found …/.android-sdk/build-tools` | `android.sdk_path` pointe vers le `.android-sdk` local, gitignoré et absent du runner | déjà corrigé : `release.yml` réécrit `android.sdk_path` vers `$ANDROIDSDK` ; ne pas réintroduire de chemin en dur |
| Le tag push passe mais aucun APK n'est uploadé | le tag ne matche pas `refs/tags/v*` | le tag doit être `v0.1` exactement (pas `0.1`, pas `release-0.1`) |
| `Permission denied` au loaddings des libs SDL | le keystore est corrompu | re-run `bash scripts/setup_keystore.sh` et re-copie les 4 secrets |

Pour toute erreur non listée : colle la sortie complète du job GitHub
Actions dans une issue ou ici, on débug ensemble.

---

## TL;DR (4 commandes dans l'ordre)

```bash
cd /home/el-hadj-ousmane/Bureau/trans_as
bash scripts/setup_keystore.sh                          # 1. keystore + alias + passwords
# → copier les 4 secrets sur https://github.com/El-hadj10/TransAs/settings/secrets/actions
git tag v0.1 && git push --tags                         # 2. tag → déclenche le build
# 3. attendre 1-3h, vérifier l'onglet Actions + Releases
gh repo edit El-hadj10/TransAs --visibility private     # 4. flip privé (ou via UI)
```
