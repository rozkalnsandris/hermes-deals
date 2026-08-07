#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH
export PYTHONDONTWRITEBYTECODE=1

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -ne 0 ]] || fail "geometry replay must run as the unprivileged andris user"
[[ "${HERMES_NETTO_GEOMETRY_REPLAY_TRIGGER:-}" == "github-actions" ]] || fail "unexpected geometry replay trigger"
[[ "${HERMES_NETTO_GEOMETRY_REPLAY_EXPECTED_HEAD:-}" =~ ^[0-9a-f]{40}$ ]] || fail "expected HEAD is invalid"
[[ -n "${HERMES_NETTO_GEOMETRY_REPLAY_EXPORT_DIR:-}" ]] || fail "geometry replay export directory is required"
[[ "${HERMES_NETTO_GEOMETRY_REPLAY_RUNTIME_ROOT:-}" == '/usr/local/libexec/hermes-deals-audits/netto-geometry-replay-v1' ]] || fail "runtime root is invalid"

EXPECTED_HEAD="$HERMES_NETTO_GEOMETRY_REPLAY_EXPECTED_HEAD"
EXPORT_DIR="$(readlink -f -- "$HERMES_NETTO_GEOMETRY_REPLAY_EXPORT_DIR")"
RUNTIME_ROOT="$HERMES_NETTO_GEOMETRY_REPLAY_RUNTIME_ROOT"
REPLAY_TOOL="$RUNTIME_ROOT/tools/netto_visual_geometry_corpus_replay.py"
PARSER_TOOL="$RUNTIME_ROOT/tools/netto_visual_geometry_shadow.py"
N10_LEDGER="$RUNTIME_ROOT/backend/tests/fixtures/netto/n10_full_visual_review_v1.json"
N9_MANIFEST='/home/andris/hermes-deals-audits/netto-n9-visual-cell-validation-pack-v1-20260802T202304Z/generated/fixture-manifest.json'
N9_SHA256='2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147'
CORPUS_ROOT='/home/andris/hermes-deals-netto-corpus/flyers'
OUTPUT="$EXPORT_DIR/netto-geometry-corpus-replay.json"
IDENTITY="$EXPORT_DIR/runtime-identity.json"

[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail "geometry replay export directory is missing or unsafe"
[[ "$EXPORT_DIR" == /home/andris/hermes-deals-runner-evidence/hermes-deals-netto-geometry-replay-* ]] || fail "geometry replay export directory is outside dedicated staging root"
[[ "$(stat -c '%U:%G' "$EXPORT_DIR")" == 'andris:andris' ]] || fail "geometry replay export directory ownership is invalid"
[[ "$(stat -c '%a' "$EXPORT_DIR")" == '700' ]] || fail "geometry replay export directory permissions must be 0700"

for path in "$REPLAY_TOOL" "$PARSER_TOOL" "$N10_LEDGER" "$N9_MANIFEST"; do
  [[ -f "$path" && ! -L "$path" ]] || fail "required replay input is missing or unsafe: $path"
done
[[ -d "$CORPUS_ROOT" && ! -L "$CORPUS_ROOT" ]] || fail "Netto corpus root is missing or unsafe"
[[ "$(sha256sum "$N9_MANIFEST" | awk '{print $1}')" == "$N9_SHA256" ]] || fail "N9 manifest SHA256 mismatch"
[[ ! -e "$OUTPUT" && ! -L "$OUTPUT" ]] || fail "replay output already exists"
[[ ! -e "$IDENTITY" && ! -L "$IDENTITY" ]] || fail "runtime identity output already exists"

PYMUPDF_VERSION="$(
  /usr/bin/python3 - <<'PY'
import importlib.metadata
import pymupdf
version = importlib.metadata.version("PyMuPDF")
if version != "1.28.0":
    raise SystemExit(f"unexpected PyMuPDF version: {version}")
print(version)
PY
)"
PYTHON_VERSION="$(/usr/bin/python3 -c 'import platform; print(platform.python_version())')"

/usr/bin/python3 - "$IDENTITY" "$EXPECTED_HEAD" "$PYTHON_VERSION" "$PYMUPDF_VERSION" "$N9_SHA256" "$RUNTIME_ROOT" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

target = Path(sys.argv[1])
expected_head = sys.argv[2]
python_version = sys.argv[3]
pymupdf_version = sys.argv[4]
n9_sha256 = sys.argv[5]
runtime_root = Path(sys.argv[6])

members = {
    "replay_tool": runtime_root / "tools/netto_visual_geometry_corpus_replay.py",
    "geometry_parser": runtime_root / "tools/netto_visual_geometry_shadow.py",
    "n10_ledger": runtime_root / "backend/tests/fixtures/netto/n10_full_visual_review_v1.json",
}
payload = {
    "schema_version": 1,
    "strategy": "netto_geometry_rpi5_replay_runtime_identity_v1",
    "registered_commit_sha": expected_head,
    "runtime_user": "andris",
    "python_executable": "/usr/bin/python3",
    "python_version": python_version,
    "pymupdf_import_name": "pymupdf",
    "pymupdf_version": pymupdf_version,
    "n9_manifest_sha256": n9_sha256,
    "production_apply_authorized": False,
    "database_write_performed": False,
    "review_write_performed": False,
    "deployment_performed": False,
    "promotion_ready": False,
    "runtime_members": {},
}
for name, path in members.items():
    payload["runtime_members"][name] = {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

/usr/bin/python3 "$REPLAY_TOOL" \
  --n9-manifest "$N9_MANIFEST" \
  --corpus-root "$CORPUS_ROOT" \
  --n10-ledger "$N10_LEDGER" \
  --output "$OUTPUT"

/usr/bin/python3 - "$OUTPUT" "$EXPECTED_HEAD" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
expected_head = sys.argv[2]
payload = json.loads(path.read_text(encoding="utf-8"))
required = {
    "strategy": "netto_visual_geometry_corpus_replay_v1",
    "geometry_parser_identity": "netto-visual-geometry-shadow-v3-unrotated-page-space",
    "source_n9_fixture_manifest_sha256": "2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147",
    "source_n10_ledger_sha256": "bf35bff323d76a2b29a7248df067641e5b9f2a7d29329cf53bf9fc0ae832734a",
    "fixture_page_count": 17,
    "cell_count": 100,
    "second_review_status": "replay_evidence_only",
    "review_only_default": True,
    "promotion_ready": False,
    "automatic_approval_enabled": False,
    "automatic_publish_enabled": False,
    "database_write_performed": False,
    "deployment_performed": False,
    "production_apply_authorized": False,
}
for key, expected in required.items():
    if payload.get(key) != expected:
        raise SystemExit(f"replay safety/identity drift: {key}={payload.get(key)!r}")
rows = payload.get("rows")
if not isinstance(rows, list) or len(rows) != 100:
    raise SystemExit("replay row count drift")
if any(row.get("promotion_ready") is not False for row in rows):
    raise SystemExit("replay row promotion flag drift")
print(
    json.dumps(
        {
            "registered_commit_sha": expected_head,
            "cell_count": payload["cell_count"],
            "geometry_binding_counts": payload.get("geometry_binding_counts"),
            "truth_comparison_counts": payload.get("truth_comparison_counts"),
            "unsafe_cross_binding_count": payload.get("unsafe_cross_binding_count"),
            "promotion_ready": payload["promotion_ready"],
        },
        sort_keys=True,
    )
)
PY
