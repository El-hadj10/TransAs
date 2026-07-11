# Security Policy

## Supported Versions

| Branch  | Status | Notes |
|---------|--------|-------|
| `main`  | :white_check_mark: Active development | Security fixes are backported as a matter of priority. |
| any other branch / fork | :x: Best-effort only | Open an issue first; we'll respond but cannot promise. |

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security bugs.**

If you discover a vulnerability in TransAs:

1. **Email** the maintainer: open a private security advisory on GitHub
   via `https://github.com/El-hadj10/TransAs/security/advisories/new`,
   **or** email the address listed in the git history's most recent commit.
2. **Encrypt** sensitive reports with the maintainer's PGP key (look in
   `.asc` files or key servers).
3. **Include**: a proof-of-concept, the affected commit/tag, and a
   description of the impact (data leak, RCE, DoS, ...).

We aim to:

- **Acknowledge** within 3 working days.
- **Triage** within 7 working days.
- **Disclose** coordinated with you, default 90 days from the report date.

We follow responsible-disclosure norms. We will credit you in the fix
commit unless you prefer anonymity.

## v0.1 Static Security Audit (this commit)

### Scope

What was reviewed in this version:

| Layer | Surface | Tooling | Pass / findings |
|-------|---------|---------|-----------------|
| Python source (`core/`, `database/`, `config.py`, `conftest.py`) | SQL injection, command injection, code injection (`eval`/`exec`), insecure deserialization (`pickle`/`yaml.unsafe_load`), insecure HTTP (`verify=False`), weak crypto hashes | ripgrep pattern sweeps on `eval/exec/shell=True/verify=False/pickle.loads/hashlib.md5` + manual source review at v0.1 cut. **Bandit + pip-audit scheduled weekly via `.github/workflows/security.yml`** (was added in this commit, will start producing CI output on the next cron tick) | **No high-severity findings** at v0.1 |
| Shell scripts (`scripts/*.sh`) | unquoted variables, `curl | bash`, weak `chmod`, insecure `wget --http`, sudo invocations | ripgrep pattern sweeps (`$\b[A-Z_]+\b`, `curl | bash`, `sudo `, `wget http://`) | **No findings** (all apt invokes are guarded by `set -euo pipefail`, scripts use `"${VAR}"` quoting idiomatically) |
| GitHub Actions (`.github/workflows/release.yml`) | expression-injection (`${{ … }}` from attacker-controlled inputs), secret leakage in run logs, dependency-pin issues | structural review | **`apksigner verify -v` paths fixed**, `JAVA_HOME` is now explicit via `actions/setup-java@v4`, dispatch `if:` simplified to push-tag-only (was unreachable) |
| Bash & shell quoting | "$VAR" missing on a positional use | ripgrep | **No findings** |
| Android manifest (`buildozer.spec`) | overbroad permissions, leakage of `package.domain` collisions | manual | Internet + ACCESS_NETWORK_STATE (justified for OSRM/Nominatim); no SMS/Contacts/Location permissions. |

### Findings (v0.1 audit pass)

All findings below are **MEDIUM-or-lower** and have been fixed in this
commit. None of them were exploitable to leak data or escalate code
execution; they were hardening improvements.

| # | File | Risk | What was fixed |
|---|------|------|----------------|
| 1 | `core/router.py` | **Medium** — fallback path used `print(...)` for OSRM failure diagnostics, leaking URL fragments / latency stats to stdout (a shared log could disclose internal infrastructure) | Replaced with `_logger.warning(...)` so log handlers can DLP/redact. |
| 2 | `core/geocoder.py` + `core/router.py` | **Medium** — `requests.get(...)` was called with a single timeout integer; a stuck TCP handshake could hang the worker thread for the full read timeout | Split into tuple `(3.05, timeout)` for connect/read. Defense-in-depth. |
| 3 | `core/geocoder.py` + `core/router.py` | **Low** — `verify=True` (TLS chain verification) was implicit (the `requests` library default) — risky if the runtime ever flipped to a non-default config | Made explicit. |
| 4 | `database/db_manager.py` | **Low/Medium** — `add_parcel(address, ...)` accepted unbounded input. A pathologically long address (megabytes), malformed lat/lon (`1e30`), or non-string crash could corrupt the database | Added `_validate_address(address)` cap at 256 chars + `_validate_coords(lat, lon)` rejecting out-of-range floats. |
| 5 | `config.py` | **Low** — `import os` was unused (`os` was imported but never referenced since `Path` is used exclusively) | Removed dead import. |

### Things we DID NOT need to fix (good news)

- **No SQL injection**: every `db_manager.py` query uses parameterized placeholders (`?`). The `update_parcel_coords`, `add_parcel`, `mark_delivered`, `load_tour_for_date`, etc. are all safe.
- **No command injection**: zero `os.system`, `subprocess.call(..., shell=True)`, `Popen(shell=True)` in the codebase.
- **No code injection**: zero `eval(`, `exec(`, `compile(` outside of (non-existent) templates.
- **No insecure deserialization**: no `pickle.loads`, no `yaml.load` with `Loader=...` defaults, no `marshal.load` on attacker-controlled bytes.
- **No insecure HTTP defaults**: every external call is HTTPS (Nominatim, OSRM) and stands up TLS chain verification by default.
- **No hardcoded credentials**: zero API keys, no passwords, no tokens in source. Secrets live in the operator's `~/.bashrc` or GitHub Actions Secrets vault.
- **No SSRF**: `OSRM_URL` and `NOMINATIM_URL` are hardcoded constants in `config.py` — there is no user-controlled URL injection surface.
- **No insecure subprocess**: zero `subprocess.Popen` / `subprocess.call` calls in production code.
- **No weak hashing for security purposes**: `hashlib.md5` / `hashlib.sha1` are NOT used (no auth/security crypto in v0.1).
- **No XML parsing**: `xml.etree` is not used (would have required `defusedxml`).
- **No tar/zip unsafe extraction**: zero `tarfile.extractall` / `zipfile.extractall` on untrusted inputs.

### What was deferred (acceptable for v0.1)

- **TLS pinning** to Nominatim/OSRM public instances. The default platform trust store is sufficient for v0.1; pinning is appropriate once we know which endpoints are stable.
- **Encrypted geocoding cache** on disk. The cache currently stores literal addresses; for v0.1 (a single deliverer's phone) this is acceptable, but v0.2+ should loop the user through `app.user_data_dir` permissions and consider per-user key derivation.
- **Per-architecture APK deterministic builds** for F-Droid verifiability. Currently Cython outputs are an ABI-stable pin (`>=0.29.36,<3.0.0`) but full bitwise reproducibility is a longer project (PR to `python-for-android` upstream).
- **Constrained sandbox on Android** via `selinux` policy hardening (`buildozer.spec` `android.private` = True). Out of scope for v0.1.

## Hardening Checklist

If you deploy or self-host TransAs, walk through:

- [ ] Generate the release keystore on an air-gapped machine.
  `bash scripts/setup_keystore.sh` then store the 4 secrets in a password
  manager (Bitwarden, KeePassXC) — never commit the `.jks` file.
- [ ] Do NOT pass `--no-verify` to git pulls (defense against rogue
  branches that might amend `buildozer.spec`).
- [ ] Run `pip-audit` monthly. CI does this weekly — see
  `.github/workflows/security.yml`.
- [ ] Run `bandit -r core database config.py`. Anything >= `High` is a
  fail. (We document this in CI.)
- [ ] Run `gitleaks detect` once before each release (catches accidentally
  pasted secrets).
- [ ] Verify the Android db-path passes `app.user_data_dir` (not the
  read-only bundled-assets dir) — see `knowledge.md` for why.

## Threat Model

TransAs is a single-tenant APK used by one courier on one phone. The
relevant threats are:

- **Adversary controls the device** (lost / stolen phone, malware): the
  path is to encrypt the SQLite db at rest in v0.2 — for v0.1 we
  document the limitation and recommend `android.app_lock` mechanisms.
- **Adversary controls the network** (rogue Wi-Fi intercepting Nominatim
  or OSRM): MITM is blocked by TLS chain verification (`verify=True`,
  applied force-default in v0.1).
- **Adversary crafts a malicious address** (DoS via huge input): bound
  by the 256-char address cap on `add_parcel` and the lat/lon range
  validators.
- **Adversary compromises CI secrets** (steals release keystore):
  mitigation = GitHub Secrets are scoped per repo + branch protection;
  rotate the keystore if compromised and document in
  `SECURITY.md` "Past advisories".
- **Adversary tampers with PyPI packages** (typosquat / dependency
  hijack): mitigated by `pip install` from a pinned `requirements.txt`
  in CI (no floating unpinned package).

Out of scope for v0.1: multi-tenant cloud backend, encrypted squelch of
historical routes on device, anti-rooting checks.
