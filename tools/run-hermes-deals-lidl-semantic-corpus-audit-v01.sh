#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

AUDIT_VERSION="lidl-semantic-corpus-audit-v01"
REPO="/home/andris/hermes-deals"
EXPECTED_ORIGIN_HTTPS="https://github.com/rozkalnsandris/hermes-deals"
EXPECTED_ORIGIN_SSH="git@github.com:rozkalnsandris/hermes-deals.git"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ "${HERMES_AUDIT_TRIGGER:-}" == "github-actions" ]] || fail "unexpected audit trigger"
[[ "${HERMES_AUDIT_EXPECTED_BRANCH:-}" == "main" ]] || fail "expected branch must be main"
[[ "${HERMES_AUDIT_EXPECTED_HEAD:-}" =~ ^[0-9a-f]{40}$ ]] || fail "expected head is invalid"
[[ -n "${HERMES_AUDIT_EXPORT_DIR:-}" ]] || fail "export directory is missing"

EXPECTED_SHA="$HERMES_AUDIT_EXPECTED_HEAD"
EXPORT_DIR="$(readlink -f -- "$HERMES_AUDIT_EXPORT_DIR")"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail "export directory is missing or unsafe"
[[ "$EXPORT_DIR" == /home/andris/hermes-deals-runner-evidence/hermes-deals-audit-* ]] || fail "export directory is outside the audit staging allowlist"
[[ "$(stat -c '%U:%G' "$EXPORT_DIR")" == "andris:andris" ]] || fail "export directory ownership is invalid"
[[ "$(stat -c '%a' "$EXPORT_DIR")" == "700" ]] || fail "export directory permissions must be 0700"

for command in diff find git python3 readlink sha256sum stat tar; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

[[ -d "$REPO/.git" ]] || fail "Hermes Deals repository is missing"
[[ "$(git -C "$REPO" branch --show-current)" == "main" ]] || fail "repository branch is not main"
[[ -z "$(git -C "$REPO" status --porcelain)" ]] || fail "repository worktree is not clean"

git -C "$REPO" cat-file -e "$EXPECTED_SHA^{commit}" || fail "registered commit is missing"
git -C "$REPO" merge-base --is-ancestor "$EXPECTED_SHA" main || fail "registered commit is not reachable from main"

origin="$(git -C "$REPO" remote get-url origin)"
case "$origin" in
  "$EXPECTED_ORIGIN_HTTPS"|"$EXPECTED_ORIGIN_HTTPS.git"|"$EXPECTED_ORIGIN_SSH") ;;
  *) fail "repository origin is not allowlisted" ;;
esac

WORK_ROOT="$(mktemp -d /home/andris/hermes-deals-runner-evidence/.lidl-semantic-audit.XXXXXX)"
cleanup() {
  rm -rf -- "$WORK_ROOT"
}
trap cleanup EXIT
install -d -m 0700 "$WORK_ROOT/code" "$WORK_ROOT/replay"

git -C "$REPO" archive --format=tar "$EXPECTED_SHA" | tar -xf - -C "$WORK_ROOT/code"
CODE_ROOT="$WORK_ROOT/code"
MANIFEST="$CODE_ROOT/tools/lidl_parser_provenance/v631/manifest.json"
SEMANTIC_TOOL="$CODE_ROOT/tools/lidl_weekly_semantic_view.py"
[[ -f "$MANIFEST" && ! -L "$MANIFEST" ]] || fail "frozen corpus manifest is missing"
[[ -f "$SEMANTIC_TOOL" && ! -L "$SEMANTIC_TOOL" ]] || fail "semantic view tool is missing"

printf '%s\n' "$EXPECTED_SHA" > "$EXPORT_DIR/registered-commit-sha.txt"
printf '%s\n' "$AUDIT_VERSION" > "$EXPORT_DIR/audit-version.txt"
sha256sum "$MANIFEST" "$SEMANTIC_TOOL" > "$EXPORT_DIR/code-input-sha256.txt"

mapfile -t bindings < <(
  python3 - "$MANIFEST" <<'PY'
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if manifest.get("schema_version") != 1:
    raise SystemExit("unsupported frozen corpus manifest schema")
rows = manifest.get("corpus_bindings")
if not isinstance(rows, list) or len(rows) < 2:
    raise SystemExit("at least two frozen corpus bindings are required")
for row in rows:
    values = [
        str(row.get("flyer_key") or ""),
        str(row.get("scan") or ""),
        str(row.get("pdf_sha256") or ""),
        str(row.get("raw_sha256") or ""),
    ]
    if not values[0] or not values[1] or any(len(value) != 64 for value in values[2:]):
        raise SystemExit("invalid frozen corpus binding")
    print("\t".join(values))
PY
)
[[ ${#bindings[@]} -ge 2 ]] || fail "frozen corpus bindings were not loaded"

find_flyer_dir() {
  local flyer_key="$1"
  local scan="$2"
  local -a matches=()
  local candidate
  while IFS= read -r candidate; do
    [[ -f "$candidate/source.pdf" ]] || continue
    [[ -f "$candidate/source.json" ]] || continue
    [[ -f "$candidate/review-profile.json" ]] || continue
    [[ -d "$candidate/scans/$scan" ]] || continue
    matches+=("$candidate")
  done < <(
    find /home/andris -xdev \
      \( -path /home/andris/.cache -o -path /home/andris/.local -o -path /home/andris/Downloads -o -path '*/.git' -o -path '*/node_modules' \) -prune -o \
      -type d -name "$flyer_key" -print 2>/dev/null
  )
  [[ ${#matches[@]} -eq 1 ]] || fail "expected exactly one complete corpus directory for $flyer_key; found ${#matches[@]}"
  printf '%s\n' "${matches[0]}"
}

mkdir -p "$EXPORT_DIR/corpora"
summary_rows="$WORK_ROOT/summary-rows.jsonl"
: > "$summary_rows"

for binding in "${bindings[@]}"; do
  IFS=$'\t' read -r flyer_key scan expected_pdf_sha expected_raw_sha <<< "$binding"
  flyer_dir="$(find_flyer_dir "$flyer_key" "$scan")"
  scan_dir="$flyer_dir/scans/$scan"

  actual_pdf_sha="$(sha256sum "$flyer_dir/source.pdf" | awk '{print $1}')"
  actual_raw_sha="$(sha256sum "$flyer_dir/source.json" | awk '{print $1}')"
  [[ "$actual_pdf_sha" == "$expected_pdf_sha" ]] || fail "PDF SHA drift for $flyer_key"
  [[ "$actual_raw_sha" == "$expected_raw_sha" ]] || fail "raw source SHA drift for $flyer_key"

  page_count="$(python3 - "$flyer_dir/source.json" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
flyer = payload.get("flyer") if isinstance(payload, dict) else None
if not isinstance(flyer, dict):
    raise SystemExit("source JSON has no flyer object")
pages = flyer.get("pages")
if not isinstance(pages, list) or not pages:
    raise SystemExit("source JSON has no page inventory")
print(len(pages))
PY
)"
  [[ "$page_count" =~ ^[1-9][0-9]*$ ]] || fail "page count is invalid for $flyer_key"

  output_dir="$EXPORT_DIR/corpora/$flyer_key/$scan/semantic-view"
  replay_dir="$WORK_ROOT/replay/$flyer_key/$scan/semantic-view"
  install -d -m 0700 "$(dirname "$output_dir")" "$(dirname "$replay_dir")"

  PYTHONPATH="$CODE_ROOT/backend" python3 "$SEMANTIC_TOOL" \
    --flyer-dir "$flyer_dir" \
    --scan-dir "$scan_dir" \
    --output-dir "$output_dir" \
    --page-count "$page_count" \
    > "$EXPORT_DIR/corpora/$flyer_key/$scan/semantic-view-result.json"

  PYTHONPATH="$CODE_ROOT/backend" python3 "$SEMANTIC_TOOL" \
    --flyer-dir "$flyer_dir" \
    --scan-dir "$scan_dir" \
    --output-dir "$replay_dir" \
    --page-count "$page_count" \
    > "$WORK_ROOT/replay-$flyer_key-$scan-result.json"

  diff -qr "$output_dir" "$replay_dir" >/dev/null || fail "semantic view is not byte-deterministic for $flyer_key/$scan"

  python3 - "$output_dir/coverage-report.json" "$output_dir/manifest.json" "$flyer_key" "$scan" "$page_count" >> "$summary_rows" <<'PY'
import hashlib
import json
import pathlib
import sys

coverage_path = pathlib.Path(sys.argv[1])
manifest_path = pathlib.Path(sys.argv[2])
flyer_key, scan, page_count = sys.argv[3], sys.argv[4], int(sys.argv[5])
coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
required_false = {
    "database_write": False,
    "review_seed": False,
    "auto_approve": False,
    "auto_publish": False,
    "production_deploy": False,
}
for key, expected in required_false.items():
    if coverage.get(key) is not expected:
        raise SystemExit(f"unsafe coverage flag {key}")
if coverage.get("unexplained_count") != 0:
    raise SystemExit("unexplained semantic rows remain")
total = int(coverage.get("row_count") or 0)
parts = sum(
    int(coverage.get(key) or 0)
    for key in ("production_ready_count", "review_required_count", "excluded_count")
)
if total <= 0 or total != parts:
    raise SystemExit("semantic row partition is incomplete")
print(json.dumps({
    "flyer_key": flyer_key,
    "scan": scan,
    "page_count": page_count,
    "row_count": total,
    "production_ready_count": int(coverage.get("production_ready_count") or 0),
    "review_required_count": int(coverage.get("review_required_count") or 0),
    "excluded_count": int(coverage.get("excluded_count") or 0),
    "unexplained_count": 0,
    "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    "deterministic_replay": True,
}, ensure_ascii=False, sort_keys=True))
PY

done

python3 - "$summary_rows" "$EXPORT_DIR/audit-summary.json" "$AUDIT_VERSION" "$EXPECTED_SHA" <<'PY'
import json
import pathlib
import sys

rows = [json.loads(line) for line in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if line.strip()]
if len(rows) < 2:
    raise SystemExit("frozen corpus audit did not cover both bindings")
payload = {
    "schema_version": 1,
    "audit_version": sys.argv[3],
    "registered_commit_sha": sys.argv[4],
    "result": "PASS",
    "corpus_binding_count": len(rows),
    "corpora": rows,
    "unexplained_count": sum(row["unexplained_count"] for row in rows),
    "deterministic_replay": all(row["deterministic_replay"] for row in rows),
    "database_write": False,
    "review_seed": False,
    "auto_approve": False,
    "auto_publish": False,
    "production_deploy": False,
    "production_apply_authorized": False,
}
pathlib.Path(sys.argv[2]).write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

find "$EXPORT_DIR" -type f -exec chmod 0600 {} +
find "$EXPORT_DIR" -type d -exec chmod 0700 {} +
printf 'AUDIT_RESULT=PASS\nAUDIT_VERSION=%s\nREGISTERED_COMMIT=%s\nCORPUS_BINDINGS=%s\nUNEXPLAINED_COUNT=0\nPRODUCTION_APPLY_AUTHORIZED=false\n' \
  "$AUDIT_VERSION" "$EXPECTED_SHA" "${#bindings[@]}"
