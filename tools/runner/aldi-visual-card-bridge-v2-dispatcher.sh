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

CONF='/etc/hermes-deals-audits.d/aldi-visual-card-bridge-v2.conf'
PRIMARY_REPO='/home/andris/hermes-deals'
ENV_VERSION_DIR='/home/andris/.local/share/hermes-deals/aldi-a30-playwright/playwright-1.61.0'
ENV_FILE="$ENV_VERSION_DIR/a30-v03.env"
DISPATCHER='/usr/local/sbin/hermes-deals-aldi-visual-card-bridge-v2'

[[ -f "$CONF" && ! -L "$CONF" ]] || fail "v2 diagnostic registration missing or unsafe"
[[ "$(stat -c '%U:%G' "$CONF")" == 'root:root' ]] || fail "v2 diagnostic registration ownership invalid"
conf_mode="$(stat -c '%a' "$CONF")"
(( (8#$conf_mode & 0022) == 0 )) || fail "v2 diagnostic registration must not be group/world writable"
# shellcheck disable=SC1090
source "$CONF"

for var in \
  registered_main_sha diagnostic_path diagnostic_sha256 producer_sha256 \
  gate_a_sha256 gate_b_sha256 gate_c_sha256 bridge_sha256 two_cycle_sha256 \
  dispatcher_sha256
do
  [[ -n "${!var:-}" ]] || fail "registration missing $var"
done

[[ "$registered_main_sha" == "$EXPECTED_MAIN_SHA" ]] || fail "registered main SHA drift"
[[ "$diagnostic_path" == '/usr/local/libexec/hermes-deals-audits/aldi-visual-card-bridge-v2/aldi_visual_card_bridge_diagnostic_v2.py' ]] || fail "v2 diagnostic path drift"
[[ "$(sha256sum "$DISPATCHER" | awk '{print $1}')" == "$dispatcher_sha256" ]] || fail "v2 dispatcher hash drift"

LIBEXEC="$(dirname "$diagnostic_path")"
[[ -f "$diagnostic_path" && ! -L "$diagnostic_path" ]] || fail "installed v2 diagnostic missing or unsafe"
[[ "$(stat -c '%U:%G' "$diagnostic_path")" == 'root:root' ]] || fail "v2 diagnostic ownership invalid"
[[ "$(sha256sum "$diagnostic_path" | awk '{print $1}')" == "$diagnostic_sha256" ]] || fail "v2 diagnostic hash drift"

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
  [[ -f "$path" && ! -L "$path" ]] || fail "installed v2 dependency missing: $name"
  [[ "$(stat -c '%U:%G' "$path")" == 'root:root' ]] || fail "v2 dependency ownership invalid: $name"
  [[ "$(sha256sum "$path" | awk '{print $1}')" == "${expected_hashes[$name]}" ]] || fail "v2 dependency hash drift: $name"
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
[[ "$EXPORT_DIR" == "/home/github-runner/_work/_temp/aldi-visual-card-bridge-v2-$GITHUB_RUN_ID" ]] || fail "artifact directory outside runner temp allowlist"
[[ "$(stat -c '%U:%G' "$EXPORT_DIR")" == 'github-runner:github-runner' ]] || fail "artifact directory ownership invalid"
[[ "$(stat -c '%a' "$EXPORT_DIR")" == '700' ]] || fail "artifact directory permissions must be 0700"
[[ -z "$(find "$EXPORT_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]] || fail "artifact directory must start empty"

install -d -o andris -g andris -m 0700 /home/andris/hermes-deals-runner-evidence
staging="$(mktemp -d /home/andris/hermes-deals-runner-evidence/aldi-visual-card-bridge-v2.XXXXXX)"
cleanup() { rm -rf -- "$staging"; }
trap cleanup EXIT
chown andris:andris "$staging"
chmod 0700 "$staging"

observed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
result="$staging/diagnostic-result.json"
set +e
runuser -u andris -- env -i \
  HOME=/home/andris USER=andris LOGNAME=andris \
  PATH=/usr/local/bin:/usr/bin:/bin \
  PYTHONPATH="$LIBEXEC" \
  PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
  "$ALDI_A30_BROWSER_PYTHON" "$diagnostic_path" \
    --source-url 'https://www.aldi-nord.de/angebote.html' \
    --browser-executable "$ALDI_A30_BROWSER_EXECUTABLE" \
    --observed-at-utc "$observed_at" \
    --output "$result"
diagnostic_rc=$?
set -e
[[ "$diagnostic_rc" -eq 0 ]] || fail "v2 diagnostic blocked: exit=$diagnostic_rc"

[[ -f "$result" && ! -L "$result" ]] || fail "v2 diagnostic result missing or unsafe"
python3 - "$result" "$EXPECTED_MAIN_SHA" "$AUTHORIZATION_COMMENT_ID" "$GITHUB_RUN_ID" "$EXPORT_DIR" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

result_path, main_sha, comment_id, run_id, export = sys.argv[1:]
payload = json.loads(Path(result_path).read_text(encoding="utf-8"))
if payload.get("schema_version") != 2:
    raise SystemExit("v2 diagnostic schema mismatch")
if payload.get("mode") != "ALDI_VISUAL_CARD_BRIDGE_DIAGNOSTIC_V02":
    raise SystemExit("v2 diagnostic mode mismatch")
if payload.get("decision") not in {
    "EXACT_ONE_TO_ONE_BRIDGE_FOUND",
    "PARTIAL_EXACT_BRIDGE_CANDIDATES",
    "NO_EXACT_VISUAL_CARD_BRIDGE",
}:
    raise SystemExit("v2 diagnostic decision rejected")
selected = int(payload.get("selected_offer_count") or 0)
cards = int(payload.get("visible_product_card_count") or 0)
if not 0 < selected <= 256 or not 0 < cards <= 512:
    raise SystemExit("v2 diagnostic counts outside bounds")
families = payload.get("families")
if not isinstance(families, list) or len(families) > 96:
    raise SystemExit("v2 family rows outside bound")
for family in families:
    if not isinstance(family, dict):
        raise SystemExit("v2 family row invalid")
    forbidden = {
        "raw_html", "outer_html", "href", "src", "value", "token_value",
        "text", "product_title", "brand", "description", "price",
    }
    if forbidden.intersection(family):
        raise SystemExit("raw bridge content exported")
    sha = str(family.get("family_fingerprint_sha256") or "")
    if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
        raise SystemExit("v2 family fingerprint invalid")
safety = payload.get("safety")
if not isinstance(safety, dict) or safety.get("diagnostic_only") is not True:
    raise SystemExit("v2 safety block missing")
for key in (
    "raw_html_exported",
    "raw_screenshot_exported",
    "raw_product_text_exported",
    "raw_href_exported",
    "raw_structured_token_exported",
    "visible_text_matching_used",
    "substring_matching_used",
    "ocr_matching_used",
    "producer_matching_contract_modified",
    "request_created",
    "request_accepted",
    "production_database_write",
    "review_publication_write",
    "source_mutation",
    "production_deploy",
    "scheduler_activation",
    "automatic_retry",
    "production_canary",
):
    if safety.get(key) is not False:
        raise SystemExit(f"unsafe v2 diagnostic flag: {key}")

sanitized = dict(payload)
sanitized.pop("safety", None)
sanitized.update({
    "authorized_main_sha": main_sha,
    "authorization_comment_id": int(comment_id),
    "github_run_id": int(run_id),
    "network_source_read": True,
    "production_database_write": False,
    "review_publication_write": False,
    "source_mutation": False,
    "production_deploy": False,
    "scheduler_activation": False,
    "automatic_retry": False,
    "request_created": False,
    "request_accepted": False,
    "production_canary": False,
})
root = Path(export)
out = root / "diagnostic-result.json"
out.write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
out.chmod(0o400)
manifest = root / "MANIFEST.sha256"
manifest.write_text(
    f"{hashlib.sha256(out.read_bytes()).hexdigest()}  diagnostic-result.json\n",
    encoding="utf-8",
)
manifest.chmod(0o400)
PY
chown github-runner:github-runner "$EXPORT_DIR/diagnostic-result.json" "$EXPORT_DIR/MANIFEST.sha256"

decision="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["decision"])' "$EXPORT_DIR/diagnostic-result.json")"
selected="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["selected_offer_count"])' "$EXPORT_DIR/diagnostic-result.json")"
cards="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["visible_product_card_count"])' "$EXPORT_DIR/diagnostic-result.json")"
bridged="$(python3 -c 'import json,sys; print((json.load(open(sys.argv[1])).get("best_family") or {}).get("bridged_offer_count",0))' "$EXPORT_DIR/diagnostic-result.json")"

printf 'DIAGNOSTIC_RESULT=PASS\nDECISION=%s\nSELECTED_OFFER_COUNT=%s\nVISIBLE_PRODUCT_CARD_COUNT=%s\nBEST_BRIDGED_OFFER_COUNT=%s\nREGISTERED_MAIN_SHA=%s\nNETWORK_SOURCE_READ=true\nPRODUCTION_DATABASE_WRITE=false\nREVIEW_PUBLICATION_WRITE=false\nSOURCE_MUTATION=false\nPRODUCTION_DEPLOYMENT=false\nSCHEDULER_ACTIVATION=false\nREQUEST_CREATED=false\nREQUEST_ACCEPTED=false\nPRODUCTION_CANARY=false\n' \
  "$decision" "$selected" "$cards" "$bridged" "$EXPECTED_MAIN_SHA"
