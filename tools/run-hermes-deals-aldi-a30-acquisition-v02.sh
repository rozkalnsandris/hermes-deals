#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

REPO="${REPO:-/home/andris/hermes-deals}"
EXPECTED_HEAD="${HERMES_AUDIT_EXPECTED_HEAD:-}"
A21_ARCHIVE="${A21_ARCHIVE:-/home/andris/.local/state/hermes-deals/aldi-perfect-shadow/hermes-deals-aldi-a21-20260801T100533Z.tar.gz}"
STATE_ROOT="${STATE_ROOT:-/home/andris/.local/state/hermes-deals/aldi-perfect-shadow}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="${RUN_DIR:-$STATE_ROOT/a30-v02-runs/$STAMP}"
INPUT_DIR="$RUN_DIR/input"
RAW_DIR="$RUN_DIR/raw"
REPORT_DIR="$RUN_DIR/reports"
OUTPUT_DIR="$RUN_DIR/audit"
LOG="$RUN_DIR/a30-v02.log"
USER_AGENT="${USER_AGENT:-HermesDeals-AldiA30Shadow/0.2 (+read-only frozen evidence)}"
IMAGE_SLEEP_SECONDS="${IMAGE_SLEEP_SECONDS:-1.4}"

fail() { printf 'FAIL %s\n' "$*" >&2; exit 1; }
pass() { printf 'PASS %s\n' "$*"; }
warn() { printf 'WARN %s\n' "$*"; }

for command in git python3 curl sha256sum awk head wc sleep; do
  command -v "$command" >/dev/null 2>&1 || fail "missing command: $command"
done
[[ -n "$EXPECTED_HEAD" ]] || fail "HERMES_AUDIT_EXPECTED_HEAD is required"
[[ -d "$REPO/.git" ]] || fail "repository not found: $REPO"
[[ -s "$A21_ARCHIVE" ]] || fail "A2.1 archive not found: $A21_ARCHIVE"

mkdir -p "$INPUT_DIR" "$RAW_DIR/viewer" "$RAW_DIR/page-images" \
  "$RAW_DIR/pdf-attempts" "$RAW_DIR/pdfs" "$REPORT_DIR" "$OUTPUT_DIR"
exec > >(tee "$LOG") 2>&1

cd "$REPO"
[[ "$(git branch --show-current)" == "main" ]] || fail "main branch required"
[[ "$(git rev-parse HEAD)" == "$EXPECTED_HEAD" ]] || fail "HEAD mismatch"
[[ -z "$(git status --porcelain=v1 --untracked-files=all)" ]] \
  || fail "repository must be clean"

printf 'mode=ALDI_A30_PINNED_SHADOW_ACQUISITION_V02\n'
printf 'production_source_write=false\n'
printf 'production_database_write=false\n'
printf 'production_deploy=false\n'
printf 'collector_execution=false\n'
printf 'viewer_html_required=false\n'

python3 - "$REPO" "$A21_ARCHIVE" "$INPUT_DIR" "$REPORT_DIR/source-plan.json" \
  "$REPORT_DIR/source-plan.tsv" "$REPORT_DIR/page-plan.tsv" <<'PY'
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys

repo = Path(sys.argv[1])
archive = Path(sys.argv[2])
input_dir = Path(sys.argv[3])
json_out = Path(sys.argv[4])
source_tsv = Path(sys.argv[5])
page_tsv = Path(sys.argv[6])

tool = repo / "tools" / "aldi_a30_frozen_acquisition.py"
spec = importlib.util.spec_from_file_location("aldi_a30_frozen_acquisition", tool)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load ALDI A3.0 audit module")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

root, integrity = module.verify_a21_archive(archive, input_dir)
plan = module.derive_source_plan(root)
plan["a21_integrity"] = integrity
json_out.write_text(
    json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

with source_tsv.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
    writer.writerow(
        ["label", "magazine_url", "ipaper_base_url", "pdf_candidate_1", "pdf_candidate_2"]
    )
    for label in ("current", "preview"):
        source = plan["sources"][label]
        magazine = source["magazine_url"]
        base = source["ipaper_base_url"]
        writer.writerow(
            [
                label,
                magazine,
                base,
                magazine.rstrip("/") + "/viewpdf.ashx",
                base.rstrip("/") + "/viewpdf.ashx",
            ]
        )

with page_tsv.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
    writer.writerow(["label", "page_number", "image_url"])
    for label in ("current", "preview"):
        for page, url in enumerate(plan["sources"][label]["image_urls"], start=1):
            writer.writerow([label, page, url])
PY
pass "exact_a21_archive_and_frozen_source_plan_verified=true"

probe_viewer() {
  local url="$1" output="$2" headers="$3" meta="$4"
  curl --location --silent --show-error --compressed \
    --retry 3 --retry-delay 2 --connect-timeout 15 --max-time 240 \
    --user-agent "$USER_AGENT" --dump-header "$headers" --output "$output" \
    --write-out $'http_code=%{http_code}\nurl_effective=%{url_effective}\ncontent_type=%{content_type}\nsize_download=%{size_download}\n' \
    "$url" > "$meta"
}

fetch_required() {
  local url="$1" output="$2" headers="$3" meta="$4"
  curl --location --fail --silent --show-error --compressed \
    --retry 3 --retry-delay 2 --connect-timeout 15 --max-time 240 \
    --user-agent "$USER_AGENT" --dump-header "$headers" --output "$output" \
    --write-out $'http_code=%{http_code}\nurl_effective=%{url_effective}\ncontent_type=%{content_type}\nsize_download=%{size_download}\n' \
    "$url" > "$meta"
}

printf 'label\tviewer_kind\turl\ttransport_ok\thttp_ok\thttp_code\tcontent_type\tsha256\tbytes\n' \
  > "$REPORT_DIR/viewer-attempts.tsv"
printf 'label\tcandidate_index\turl\thttp_ok\tpdf_magic\tselected\tsha256\tbytes\n' \
  > "$REPORT_DIR/pdf-attempts.tsv"

tail -n +2 "$REPORT_DIR/source-plan.tsv" |
while IFS=$'\t' read -r label magazine_url ipaper_base pdf1 pdf2; do
  mkdir -p "$RAW_DIR/viewer/$label" "$RAW_DIR/pdf-attempts/$label"
  for viewer_kind in magazine ipaper; do
    [[ "$viewer_kind" == "magazine" ]] && url="$magazine_url" || url="$ipaper_base"
    output="$RAW_DIR/viewer/$label/$viewer_kind.html"
    headers="$RAW_DIR/viewer/$label/$viewer_kind.headers"
    meta="$RAW_DIR/viewer/$label/$viewer_kind.meta"
    transport_ok=false
    http_ok=false
    http_code=000
    content_type=""
    file_sha=""
    bytes=0
    if probe_viewer "$url" "$output" "$headers" "$meta"; then
      transport_ok=true
      http_code="$(awk -F= '$1=="http_code"{print $2}' "$meta" | tail -n1)"
      content_type="$(awk -F= '$1=="content_type"{sub(/^content_type=/,"");print}' "$meta" | tail -n1)"
      [[ "$http_code" =~ ^[23][0-9][0-9]$ ]] && http_ok=true
      if [[ -f "$output" ]]; then
        file_sha="$(sha256sum "$output" | awk '{print $1}')"
        bytes="$(wc -c < "$output" | tr -d ' ')"
      fi
    else
      warn "viewer transport failed but is advisory: $label/$viewer_kind"
    fi
    [[ "$http_ok" == "true" ]] \
      || warn "expired/unavailable viewer is non-fatal: $label/$viewer_kind HTTP $http_code"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$label" "$viewer_kind" "$url" "$transport_ok" "$http_ok" \
      "$http_code" "$content_type" "$file_sha" "$bytes" \
      >> "$REPORT_DIR/viewer-attempts.tsv"
  done

  selected=false
  index=0
  for url in "$pdf1" "$pdf2"; do
    index=$((index + 1))
    output="$RAW_DIR/pdf-attempts/$label/candidate-$index.bin"
    headers="$RAW_DIR/pdf-attempts/$label/candidate-$index.headers"
    meta="$RAW_DIR/pdf-attempts/$label/candidate-$index.meta"
    http_ok=false
    pdf_magic=false
    selected_this=false
    file_sha=""
    bytes=0
    if fetch_required "$url" "$output" "$headers" "$meta"; then
      http_ok=true
      file_sha="$(sha256sum "$output" | awk '{print $1}')"
      bytes="$(wc -c < "$output" | tr -d ' ')"
      if [[ "$(head -c 5 "$output" 2>/dev/null || true)" == "%PDF-" ]]; then
        pdf_magic=true
        if [[ "$selected" == "false" ]]; then
          cp -f "$output" "$RAW_DIR/pdfs/$label.pdf"
          selected=true
          selected_this=true
        fi
      fi
    else
      warn "official PDF candidate unavailable: $label/$index"
      rm -f "$output"
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$label" "$index" "$url" "$http_ok" "$pdf_magic" \
      "$selected_this" "$file_sha" "$bytes" \
      >> "$REPORT_DIR/pdf-attempts.tsv"
  done
done
pass "viewer_probes_recorded_as_advisory=true"
pass "official_pdf_candidates_probed_as_optional=true"

tail -n +2 "$REPORT_DIR/page-plan.tsv" |
while IFS=$'\t' read -r label page image_url; do
  directory="$RAW_DIR/page-images/$label"
  mkdir -p "$directory"
  padded="$(printf '%03d' "$page")"
  fetch_required \
    "$image_url" \
    "$directory/page-$padded.img" \
    "$directory/page-$padded.headers" \
    "$directory/page-$padded.meta"
  sleep "$IMAGE_SLEEP_SECONDS"
done
pass "all_frozen_page_image_requests_completed=true"

python3 - "$REPORT_DIR/page-plan.tsv" "$RAW_DIR/page-images" \
  "$REPORT_DIR/page-image-manifest.json" <<'PY'
from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path
import sys

plan = Path(sys.argv[1])
root = Path(sys.argv[2])
output = Path(sys.argv[3])
rows = []
with plan.open(encoding="utf-8", newline="") as handle:
    for item in csv.DictReader(handle, delimiter="\t"):
        label = item["label"]
        page = int(item["page_number"])
        path = root / label / f"page-{page:03d}.img"
        data = path.read_bytes()
        if len(data) < 10_000:
            raise SystemExit(f"implausibly small page image: {label}:{page}")
        if data.startswith(b"\xff\xd8"):
            image_format = "jpeg"
        elif data.startswith(b"\x89PNG\r\n\x1a\n"):
            image_format = "png"
        elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            image_format = "webp"
        else:
            raise SystemExit(f"unknown page image format: {label}:{page}")
        rows.append(
            {
                "label": label,
                "page_number": page,
                "image_url": item["image_url"],
                "format": image_format,
                "bytes": len(data),
                "sha256": sha256(data).hexdigest(),
            }
        )
output.write_text(
    json.dumps({"strategy": "frozen_official_ipaper_pages", "rows": rows},
               ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

python3 - "$RAW_DIR/pdfs" "$REPORT_DIR/pdf-text-summary.json" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
output = Path(sys.argv[2])
documents = {}
backend = "none"
try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

if PdfReader is not None:
    backend = "pypdf"
    for label in ("current", "preview"):
        path = root / f"{label}.pdf"
        if not path.is_file():
            continue
        reader = PdfReader(str(path))
        pages_with_text = 0
        for page in reader.pages:
            if "".join((page.extract_text() or "").split()):
                pages_with_text += 1
        documents[label] = {
            "page_count": len(reader.pages),
            "pages_with_any_text": pages_with_text,
        }

output.write_text(
    json.dumps(
        {"backend": backend, "documents": documents},
        ensure_ascii=False, indent=2, sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)
PY

python3 "$REPO/tools/aldi_a30_frozen_acquisition.py" \
  --archive "$A21_ARCHIVE" \
  --page-manifest "$REPORT_DIR/page-image-manifest.json" \
  --viewer-attempts "$REPORT_DIR/viewer-attempts.tsv" \
  --pdf-attempts "$REPORT_DIR/pdf-attempts.tsv" \
  --pdf-text-summary "$REPORT_DIR/pdf-text-summary.json" \
  --output "$OUTPUT_DIR" \
  --commit-sha "$EXPECTED_HEAD"

[[ -z "$(git status --porcelain=v1 --untracked-files=all)" ]] \
  || fail "audit changed repository worktree"
pass "production_repository_unchanged=true"
pass "production_database_unchanged_by_construction=true"
pass "production_runtime_unchanged_by_construction=true"
printf 'RESULT=ALDI_A30_PINNED_SHADOW_ACQUISITION_V02_PASS\n'
printf 'RUN_DIR=%s\n' "$RUN_DIR"
printf 'LOG=%s\n' "$LOG"
