#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "dispatcher must run as root"
[[ $# -eq 4 ]] || fail "usage: dispatcher <expected-main-sha> <authorization-comment-id> <github-run-id> <artifact-dir>"

EXPECTED_MAIN_SHA="$1"
AUTHORIZATION_COMMENT_ID="$2"
GITHUB_RUN_ID="$3"
EXPORT_DIR="$4"

[[ "$EXPECTED_MAIN_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid expected main SHA"
[[ "$AUTHORIZATION_COMMENT_ID" =~ ^[1-9][0-9]*$ ]] || fail "invalid authorization comment id"
[[ "$GITHUB_RUN_ID" =~ ^[1-9][0-9]*$ ]] || fail "invalid GitHub run id"

CONF='/etc/hermes-deals-audits.d/aldi-new-baseline-weekly-shadow-producer.conf'
PRIMARY_REPO='/home/andris/hermes-deals'
REQUEST_ROOT='/var/lib/hermes-deals/aldi-new-baseline-weekly-shadow-v01/requests'
EVIDENCE_ROOT='/var/lib/hermes-deals/aldi-new-baseline-weekly-shadow-v01/evidence'
ENV_VERSION_DIR='/home/andris/.local/share/hermes-deals/aldi-a30-playwright/playwright-1.61.0'
ENV_FILE="$ENV_VERSION_DIR/a30-v03.env"
DISPATCHER='/usr/local/sbin/hermes-deals-aldi-new-baseline-weekly-shadow-producer-dispatch'

[[ -f "$CONF" && ! -L "$CONF" ]] || fail "producer registration missing or unsafe"
[[ "$(stat -c '%U:%G' "$CONF")" == 'root:root' ]] || fail "producer registration ownership invalid"
conf_mode="$(stat -c '%a' "$CONF")"
(( (8#$conf_mode & 0022) == 0 )) || fail "producer registration must not be group/world writable"
# shellcheck disable=SC1090
source "$CONF"

for var in \
  registered_main_sha producer_path producer_sha256 \
  gate_a_sha256 gate_b_sha256 gate_c_sha256 bridge_sha256 \
  two_cycle_sha256 dispatcher_sha256
do
  [[ -n "${!var:-}" ]] || fail "registration missing $var"
done

[[ "$registered_main_sha" == "$EXPECTED_MAIN_SHA" ]] || fail "registered main SHA drift"
[[ "$producer_path" == '/usr/local/libexec/hermes-deals-audits/aldi-new-baseline-weekly-shadow-producer-v01/aldi_new_baseline_weekly_shadow_producer.py' ]] || fail "producer path drift"
[[ "$(sha256sum "$DISPATCHER" | awk '{print $1}')" == "$dispatcher_sha256" ]] || fail "dispatcher hash drift"

LIBEXEC="$(dirname "$producer_path")"
declare -A expected_hashes=(
  [aldi_new_baseline_weekly_shadow_producer.py]="$producer_sha256"
  [aldi_new_immutable_baseline_gate.py]="$gate_a_sha256"
  [aldi_new_baseline_page_card_parity.py]="$gate_b_sha256"
  [aldi_new_baseline_gate_c_replay.py]="$gate_c_sha256"
  [aldi_new_baseline_weekly_shadow_bridge.py]="$bridge_sha256"
  [aldi_new_baseline_two_cycle_shadow_gate.py]="$two_cycle_sha256"
)
for name in "${!expected_hashes[@]}"; do
  path="$LIBEXEC/$name"
  [[ -f "$path" && ! -L "$path" ]] || fail "installed producer member missing: $name"
  [[ "$(stat -c '%U:%G' "$path")" == 'root:root' ]] || fail "installed producer member ownership invalid: $name"
  [[ "$(sha256sum "$path" | awk '{print $1}')" == "${expected_hashes[$name]}" ]] || fail "installed producer member hash drift: $name"
done

[[ -d "$PRIMARY_REPO/.git" && ! -L "$PRIMARY_REPO/.git" ]] || fail "primary repository missing or unsafe"
git_read() {
  runuser -u andris -- env -i \
    HOME=/home/andris USER=andris LOGNAME=andris \
    PATH=/usr/local/bin:/usr/bin:/bin \
    GIT_OPTIONAL_LOCKS=0 \
    git -C "$PRIMARY_REPO" "$@"
}
[[ "$(git_read branch --show-current)" == main ]] || fail "primary repository is not on main"
[[ -z "$(git_read status --porcelain=v1 --untracked-files=all)" ]] || fail "primary repository is dirty"
[[ "$(git_read rev-parse HEAD)" == "$EXPECTED_MAIN_SHA" ]] || fail "primary main drift"
origin="$(git_read remote get-url origin)"
case "$origin" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "primary origin is not allowlisted" ;;
esac

[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "isolated Playwright environment missing or unsafe"
python3 - "$ENV_FILE" "$ENV_VERSION_DIR" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
root = Path(sys.argv[2]).resolve()
lines = [
    line.strip()
    for line in path.read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.lstrip().startswith("#")
]
expected = {
    "ALDI_A30_BROWSER_PYTHON",
    "ALDI_A30_BROWSER_EXECUTABLE",
    "PLAYWRIGHT_BROWSERS_PATH",
}
values = {}
pattern = re.compile(r"^export ([A-Z0-9_]+)='([^']+)'$")
for line in lines:
    match = pattern.fullmatch(line)
    if not match:
        raise SystemExit(f"unsafe environment line: {line}")
    name, value = match.groups()
    if name in values:
        raise SystemExit(f"duplicate environment variable: {name}")
    values[name] = value
if set(values) != expected:
    raise SystemExit("Playwright environment variable contract mismatch")
for name, value in values.items():
    resolved = Path(value).resolve()
    if root != resolved and root not in resolved.parents:
        raise SystemExit(f"{name} escapes isolated environment root")
PY
# shellcheck disable=SC1090
source "$ENV_FILE"
[[ -x "$ALDI_A30_BROWSER_PYTHON" ]] || fail "isolated Playwright Python missing"
[[ -x "$ALDI_A30_BROWSER_EXECUTABLE" ]] || fail "isolated Chromium missing"
[[ -d "$PLAYWRIGHT_BROWSERS_PATH" && ! -L "$PLAYWRIGHT_BROWSERS_PATH" ]] || fail "isolated browser cache missing or unsafe"
[[ "$("$ALDI_A30_BROWSER_PYTHON" -c 'from importlib.metadata import version; print(version("playwright"))')" == "1.61.0" ]] || fail "Playwright version drift"

EXPORT_DIR="$(readlink -f -- "$EXPORT_DIR")"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail "artifact directory missing or unsafe"
[[ "$EXPORT_DIR" == "/home/github-runner/_work/_temp/aldi-new-baseline-weekly-shadow-producer-$GITHUB_RUN_ID" ]] || fail "artifact directory outside runner temp allowlist"
[[ "$(stat -c '%U:%G' "$EXPORT_DIR")" == 'github-runner:github-runner' ]] || fail "artifact directory ownership invalid"
[[ "$(stat -c '%a' "$EXPORT_DIR")" == '700' ]] || fail "artifact directory permissions must be 0700"
[[ -z "$(find "$EXPORT_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]] || fail "artifact directory must start empty"

install -d -o andris -g andris -m 0700 /home/andris/hermes-deals-runner-evidence
staging="$(mktemp -d /home/andris/hermes-deals-runner-evidence/aldi-new-baseline-producer.XXXXXX)"
cleanup() { rm -rf -- "$staging"; }
trap cleanup EXIT
chown andris:andris "$staging"
chmod 0700 "$staging"

observed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
set +e
runuser -u andris -- env -i \
  HOME=/home/andris USER=andris LOGNAME=andris \
  PATH=/usr/local/bin:/usr/bin:/bin \
  PYTHONPATH="$LIBEXEC" \
  PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
  "$ALDI_A30_BROWSER_PYTHON" "$producer_path" \
    --source-url 'https://www.aldi-nord.de/angebote.html' \
    --browser-executable "$ALDI_A30_BROWSER_EXECUTABLE" \
    --observed-at-utc "$observed_at" \
    --authorized-main-sha "$EXPECTED_MAIN_SHA" \
    --repo-root "$PRIMARY_REPO" \
    --output "$staging/output"
producer_rc=$?
set -e
[[ "$producer_rc" -eq 0 ]] || fail "producer blocked: exit=$producer_rc"

request_file="$staging/output/request/request.json"
[[ -f "$request_file" && ! -L "$request_file" ]] || fail "producer request.json missing"
request_sha="$(sha256sum "$request_file" | awk '{print $1}')"
[[ "$request_sha" =~ ^[0-9a-f]{64}$ ]] || fail "producer request SHA invalid"

dest="$REQUEST_ROOT/$request_sha"
evidence_dest="$EVIDENCE_ROOT/$request_sha"
[[ ! -e "$dest" ]] || fail "request already exists"
[[ ! -e "$evidence_dest" ]] || fail "evidence already exists"
install -d -o root -g root -m 0700 "$REQUEST_ROOT" "$EVIDENCE_ROOT"
install -d -o root -g root -m 0700 "$dest" "$evidence_dest"

for name in request.json gate-a-input.json gate-b-input.json gate-c-input.json execution-evidence.json; do
  src="$staging/output/request/$name"
  [[ -f "$src" && ! -L "$src" ]] || fail "required request member missing: $name"
  install -o root -g root -m 0400 "$src" "$dest/$name"
done
[[ "$(sha256sum "$dest/request.json" | awk '{print $1}')" == "$request_sha" ]] || fail "installed request SHA drift"

for name in official-source.html official-render.png; do
  src="$staging/output/capture/$name"
  [[ -f "$src" && ! -L "$src" ]] || fail "required immutable capture missing: $name"
  install -o root -g root -m 0400 "$src" "$evidence_dest/$name"
done

python3 - "$dest/gate-a-input.json" "$evidence_dest/official-source.html" "$evidence_dest/official-render.png" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

gate = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
source_path = Path(sys.argv[2])
render_path = Path(sys.argv[3])
sources = gate.get("sources")
manifest = (gate.get("page_manifest") or {}).get("pages")
if not isinstance(sources, list) or len(sources) != 1:
    raise SystemExit("Gate A source evidence shape mismatch")
if not isinstance(manifest, list) or len(manifest) != 1:
    raise SystemExit("Gate A visual evidence shape mismatch")
source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
render_sha = hashlib.sha256(render_path.read_bytes()).hexdigest()
if sources[0].get("sha256") != source_sha:
    raise SystemExit("retained official source SHA mismatch")
if manifest[0].get("sha256") != render_sha:
    raise SystemExit("retained official render SHA mismatch")
PY

{
  sha256sum "$evidence_dest/official-source.html"
  sha256sum "$evidence_dest/official-render.png"
} | sed "s#  $evidence_dest/#  #" > "$evidence_dest/EVIDENCE.sha256"
chown root:root "$evidence_dest/EVIDENCE.sha256"
chmod 0400 "$evidence_dest/EVIDENCE.sha256"
evidence_manifest_sha="$(sha256sum "$evidence_dest/EVIDENCE.sha256" | awk '{print $1}')"

result="$staging/output/producer-result.json"
[[ -f "$result" && ! -L "$result" ]] || fail "producer result missing"
python3 - "$result" "$request_sha" "$EXPECTED_MAIN_SHA" "$AUTHORIZATION_COMMENT_ID" "$GITHUB_RUN_ID" "$evidence_manifest_sha" "$EXPORT_DIR" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

(
    result_path,
    request_sha,
    main_sha,
    comment_id,
    run_id,
    evidence_manifest_sha,
    export,
) = sys.argv[1:]
payload = json.loads(Path(result_path).read_text(encoding="utf-8"))
if payload.get("decision") != "REQUEST_PREPARED":
    raise SystemExit("producer result is not REQUEST_PREPARED")
if payload.get("request_sha256") != request_sha:
    raise SystemExit("producer result/request mismatch")
for key in (
    "production_database_write",
    "review_publication_write",
    "source_mutation",
    "production_deploy",
    "scheduler_activation",
    "automatic_retry",
):
    if payload.get(key) is not False:
        raise SystemExit(f"unsafe producer flag: {key}")

sanitized = {
    "schema_version": 1,
    "decision": "REQUEST_PREPARED",
    "request_sha256": request_sha,
    "authorized_main_sha": main_sha,
    "authorization_comment_id": int(comment_id),
    "github_run_id": int(run_id),
    "iso_week": payload.get("iso_week"),
    "baseline_id": payload.get("baseline_id"),
    "source_url": payload.get("source_url"),
    "evidence_manifest_sha256": evidence_manifest_sha,
    "immutable_evidence_retained": True,
    "production_database_write": False,
    "review_publication_write": False,
    "source_mutation": False,
    "production_deploy": False,
    "scheduler_activation": False,
    "automatic_retry": False,
}
root = Path(export)
out = root / "producer-result.json"
out.write_text(
    json.dumps(sanitized, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
out.chmod(0o400)
manifest = root / "MANIFEST.sha256"
manifest.write_text(
    f"{hashlib.sha256(out.read_bytes()).hexdigest()}  producer-result.json\n",
    encoding="utf-8",
)
manifest.chmod(0o400)
PY
chown github-runner:github-runner "$EXPORT_DIR/producer-result.json" "$EXPORT_DIR/MANIFEST.sha256"

printf 'PRODUCER_RESULT=PASS\nREQUEST_SHA256=%s\nREGISTERED_MAIN_SHA=%s\nIMMUTABLE_EVIDENCE_RETAINED=true\nEVIDENCE_MANIFEST_SHA256=%s\nPRODUCTION_DATABASE_WRITE=false\nREVIEW_PUBLICATION_WRITE=false\nSOURCE_MUTATION=false\nPRODUCTION_DEPLOYMENT=false\nSCHEDULER_ACTIVATION=false\n' \
  "$request_sha" "$EXPECTED_MAIN_SHA" "$evidence_manifest_sha"
