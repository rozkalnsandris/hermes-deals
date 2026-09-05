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

CONF='/etc/hermes-deals-audits.d/aldi-visual-identity-carrier-diagnostic.conf'
PRIMARY_REPO='/home/andris/hermes-deals'
ENV_VERSION_DIR='/home/andris/.local/share/hermes-deals/aldi-a30-playwright/playwright-1.61.0'
ENV_FILE="$ENV_VERSION_DIR/a30-v03.env"
DISPATCHER='/usr/local/sbin/hermes-deals-aldi-visual-identity-carrier-diagnostic'

[[ -f "$CONF" && ! -L "$CONF" ]] || fail "diagnostic registration missing or unsafe"
[[ "$(stat -c '%U:%G' "$CONF")" == 'root:root' ]] || fail "diagnostic registration ownership invalid"
conf_mode="$(stat -c '%a' "$CONF")"
(( (8#$conf_mode & 0022) == 0 )) || fail "diagnostic registration must not be group/world writable"
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
[[ "$diagnostic_path" == '/usr/local/libexec/hermes-deals-audits/aldi-visual-identity-carrier-diagnostic-v01/aldi_visual_identity_carrier_diagnostic.py' ]] || fail "diagnostic path drift"
[[ "$(sha256sum "$DISPATCHER" | awk '{print $1}')" == "$dispatcher_sha256" ]] || fail "dispatcher hash drift"

LIBEXEC="$(dirname "$diagnostic_path")"
[[ -f "$diagnostic_path" && ! -L "$diagnostic_path" ]] || fail "installed diagnostic missing or unsafe"
[[ "$(stat -c '%U:%G' "$diagnostic_path")" == 'root:root' ]] || fail "diagnostic ownership invalid"
[[ "$(sha256sum "$diagnostic_path" | awk '{print $1}')" == "$diagnostic_sha256" ]] || fail "diagnostic hash drift"

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
  [[ -f "$path" && ! -L "$path" ]] || fail "installed diagnostic dependency missing: $name"
  [[ "$(stat -c '%U:%G' "$path")" == 'root:root' ]] || fail "diagnostic dependency ownership invalid: $name"
  [[ "$(sha256sum "$path" | awk '{print $1}')" == "${expected_hashes[$name]}" ]] || fail "diagnostic dependency hash drift: $name"
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
[[ "$EXPORT_DIR" == "/home/github-runner/_work/_temp/aldi-visual-identity-carrier-diagnostic-$GITHUB_RUN_ID" ]] || fail "artifact directory outside runner temp allowlist"
[[ "$(stat -c '%U:%G' "$EXPORT_DIR")" == 'github-runner:github-runner' ]] || fail "artifact directory ownership invalid"
[[ "$(stat -c '%a' "$EXPORT_DIR")" == '700' ]] || fail "artifact directory permissions must be 0700"
[[ -z "$(find "$EXPORT_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]] || fail "artifact directory must start empty"

install -d -o andris -g andris -m 0700 /home/andris/hermes-deals-runner-evidence
staging="$(mktemp -d /home/andris/hermes-deals-runner-evidence/aldi-identity-carrier-diagnostic.XXXXXX)"
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
[[ "$diagnostic_rc" -eq 0 ]] || fail "diagnostic blocked: exit=$diagnostic_rc"

[[ -f "$result" && ! -L "$result" ]] || fail "diagnostic result missing or unsafe"
python3 - "$result" "$EXPECTED_MAIN_SHA" "$AUTHORIZATION_COMMENT_ID" "$GITHUB_RUN_ID" "$EXPORT_DIR" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

result_path, main_sha, comment_id, run_id, export = sys.argv[1:]
payload = json.loads(Path(result_path).read_text(encoding="utf-8"))
if payload.get("schema_version") != 1:
    raise SystemExit("diagnostic schema mismatch")
if payload.get("mode") != "ALDI_VISUAL_IDENTITY_CARRIER_DIAGNOSTIC_V01":
    raise SystemExit("diagnostic mode mismatch")
if payload.get("decision") not in {
    "NO_UNBOUND_OFFERS",
    "ALL_UNBOUND_HAVE_DOM_IDENTITY_CARRIERS",
    "PARTIAL_DOM_IDENTITY_CARRIERS",
    "NO_DOM_IDENTITY_CARRIERS",
}:
    raise SystemExit("diagnostic decision rejected")
safety = payload.get("safety")
if not isinstance(safety, dict) or safety.get("diagnostic_only") is not True:
    raise SystemExit("diagnostic safety block missing")
for key in (
    "raw_html_exported",
    "raw_screenshot_exported",
    "raw_product_text_exported",
    "raw_href_exported",
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
        raise SystemExit(f"unsafe diagnostic flag: {key}")
rows = payload.get("rows")
if not isinstance(rows, list) or len(rows) > 256:
    raise SystemExit("diagnostic rows outside bound")
for row in rows:
    if not isinstance(row, dict) or not str(row.get("object_id") or "").isdigit():
        raise SystemExit("diagnostic objectID row invalid")
    samples = row.get("samples")
    if not isinstance(samples, list) or len(samples) > 12:
        raise SystemExit("carrier samples outside bound")
    for sample in samples:
        if not isinstance(sample, dict):
            raise SystemExit("carrier sample invalid")
        forbidden = {"raw_html", "outer_html", "href", "src", "text", "product_title", "price"}
        if forbidden.intersection(sample):
            raise SystemExit("raw carrier content exported")
        sha = str(sample.get("carrier_fingerprint_sha256") or "")
        if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            raise SystemExit("carrier fingerprint invalid")

sanitized = {
    "schema_version": 1,
    "decision": payload["decision"],
    "authorized_main_sha": main_sha,
    "authorization_comment_id": int(comment_id),
    "github_run_id": int(run_id),
    "observed_at_utc": payload.get("observed_at_utc"),
    "source_url": payload.get("source_url"),
    "source_sha256": payload.get("source_sha256"),
    "iso_week": payload.get("iso_week"),
    "valid_from": payload.get("valid_from"),
    "valid_until": payload.get("valid_until"),
    "week_view_label": payload.get("week_view_label"),
    "selected_offer_count": payload.get("selected_offer_count"),
    "unbound_offer_count": payload.get("unbound_offer_count"),
    "unbound_with_dom_identity_carrier_count": payload.get("unbound_with_dom_identity_carrier_count"),
    "unbound_script_only_count": payload.get("unbound_script_only_count"),
    "unbound_without_any_observed_carrier_count": payload.get("unbound_without_any_observed_carrier_count"),
    "document": payload.get("document"),
    "rows": rows,
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
}
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
unbound="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["unbound_offer_count"])' "$EXPORT_DIR/diagnostic-result.json")"
with_dom="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["unbound_with_dom_identity_carrier_count"])' "$EXPORT_DIR/diagnostic-result.json")"

printf 'DIAGNOSTIC_RESULT=PASS\nDECISION=%s\nUNBOUND_OFFER_COUNT=%s\nUNBOUND_WITH_DOM_IDENTITY_CARRIER_COUNT=%s\nREGISTERED_MAIN_SHA=%s\nNETWORK_SOURCE_READ=true\nPRODUCTION_DATABASE_WRITE=false\nREVIEW_PUBLICATION_WRITE=false\nSOURCE_MUTATION=false\nPRODUCTION_DEPLOYMENT=false\nSCHEDULER_ACTIVATION=false\nREQUEST_CREATED=false\nREQUEST_ACCEPTED=false\nPRODUCTION_CANARY=false\n' \
  "$decision" "$unbound" "$with_dom" "$EXPECTED_MAIN_SHA"
