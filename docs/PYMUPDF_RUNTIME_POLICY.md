# PyMuPDF runtime identity policy

This policy applies to Hermes Deals code, installers, audit runners, self-hosted GitHub Actions helpers and RPi5 maintenance scripts that use PyMuPDF.

## Why this exists

A dependency check is valid only when it proves the environment that will actually execute the workload.

On 2026-08-07 the Netto geometry replay installer was launched with `sudo`. Its PyMuPDF preflight therefore executed `/usr/bin/python3` as `root`, while the real replay was intentionally designed to execute as the unprivileged `andris` user. The host had the required PyMuPDF runtime for `andris`, but the root environment did not expose it, so the installer failed with `ModuleNotFoundError: No module named 'fitz'` before any runtime or dispatcher was installed.

The failure was in the preflight identity, not evidence that the RPi5 needed a new root-level Python package installation.

## Canonical import

Use the current PyMuPDF package name in new and maintained code:

```python
import pymupdf
```

Do not add new `import fitz` usage. `fitz` is PyMuPDF's legacy import alias and can collide with an unrelated PyPI package also named `fitz`.

Never install the unrelated `fitz` package as a way to repair PyMuPDF.

When checking the installed PyMuPDF distribution version, use the distribution name:

```python
import importlib.metadata
import pymupdf

version = importlib.metadata.version("PyMuPDF")
```

## Runtime identity rule

A Python dependency preflight must match all of the following properties of the real workload:

1. exact OS user;
2. exact Python executable;
3. relevant environment isolation, including `HOME` and user-site visibility;
4. required package version;
5. import name used by maintained code.

For an RPi5 workload that runs as `andris` with `/usr/bin/python3`, a privileged installer or dispatcher must not validate PyMuPDF by running root's plain `/usr/bin/python3`.

The check must execute as the runtime user, for example:

```bash
runuser -u andris -- /usr/bin/env -i \
  HOME=/home/andris \
  USER=andris \
  LOGNAME=andris \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/python3 - <<'PY'
import importlib.metadata
import pymupdf

version = importlib.metadata.version("PyMuPDF")
if version != "1.28.0":
    raise SystemExit(f"PyMuPDF 1.28.0 required, found {version}")
PY
```

The version value above is an example of an evidence-bound runtime contract. A different workflow may pin a different reviewed version, but the user/interpreter identity rule does not change.

## Privileged wrapper rule

A root-owned installer or dispatcher may verify files, ownership, hashes, sudoers rules and other privileged state as root. It must switch to the workload user for checks whose result depends on that user's Python environment.

Do not solve a user-environment mismatch by installing Python packages into root's environment unless root is itself the reviewed workload identity.

## Installation rule

Audit preflights and replay control planes are verification paths, not package-management paths.

They must fail closed on a missing/wrong PyMuPDF runtime. They must not run `pip install`, `pip uninstall`, `apt install` or otherwise mutate the Python environment as part of an audit execution.

If a runtime dependency genuinely needs installation or upgrade, handle that as a separate reviewed maintenance change with its own evidence and authorization.

## CI and self-hosted host checks

GitHub-hosted CI can verify source contracts and tests, but it does not prove which user-site packages are visible on the RPi5.

For a self-hosted workload, the final host preflight must validate the exact runtime identity on the host. Record at minimum:

- runtime user;
- Python executable;
- Python version;
- PyMuPDF version;
- canonical import name;
- exact registered commit/runtime hashes when applicable.

## Review checklist

Before approving a PyMuPDF-related installer or runner change, verify:

- no new legacy `import fitz` in maintained runtime/preflight code;
- no accidental installation of the unrelated `fitz` PyPI package;
- dependency checks execute as the real workload user;
- dependency checks use the real workload Python executable;
- privileged wrappers do not silently substitute root's Python environment;
- no audit-time package installation;
- focused regression tests pin these rules.

This policy is intended to prevent the same class of environment-identity mistake from recurring across Netto, Lidl, ALDI, EDEKA and future Hermes Deals PDF workflows.
