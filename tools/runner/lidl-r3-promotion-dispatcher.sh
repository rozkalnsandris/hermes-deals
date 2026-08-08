#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'dispatcher must run as root through sudo'
[[ $# -eq 2 ]] || fail 'usage: dispatcher <registered-sha> <artifact-dir>'
REGISTERED_SHA="$1"
ARTIFACT_DIR="$2"

CONF='/etc/hermes-deals-audits.d/lidl-r3-promotion.conf'
LIBEXEC='/usr/local/libexec/hermes-deals-r3'
APPLY_TOOL="$LIBEXEC/lidl_source_refresh_r3_apply.py"
PLAN_TOOL="$LIBEXEC/lidl_source_refresh_r3_plan.py"
PLAN_V2_TOOL="$LIBEXEC/lidl_source_refresh_r3_plan_v2.py"
AUDIT_TOOL='/usr/local/libexec/hermes-deals-audits/lidl-source-refresh-audit.py'
AUDIT_TOOL_SHA='3ff8e244b463fb62ef632f8a8cf3be78012a7e72f6b36606a519590b7b634222'
DISPATCHER='/usr/local/sbin/hermes-deals-lidl-r3-promotion-dispatch'
CORPUS_ROOT='/home/andris/hermes-deals-lidl-corpus'
FAMILY="$CORPUS_ROOT/flyers/aktionsprospekt-03-08-2026-08-08-2026-b1cf3b--src-6da2135ea984"
SCAN_TARGET="$FAMILY/scans/scan-v631-7191e910f07b"
REFRESH_TARGET="$FAMILY/source-refresh/e6ebe5669551a2d455e7b2c036746e08e3bdd20e8e0562fab6972ab97e2a88e8"
PROFILE="$FAMILY/review-profile.json"
PRIMARY='/home/andris/hermes-deals'
V08_SCRIPT="$PRIMARY/tools/run-hermes-deals-b15m2-least-privilege-shadow-migration-api-regression-v08.sh"
PRIVATE_ROOT='/home/andris/hermes-deals-r3-promotion-evidence'
R2_SHA='d4f9be1a19592a45739e4cc6a2827833682460e1c41bdd6496e0375077ef33c4'
R3_SHA='c1432c05d3975094d2e56ae70fc216c8e8def4199ac312c92b2ff50afc9032dc'
PDF_SHA='6da2135ea984d1f79bdb311dfa0d8affd1d2f8d46c63a1bba25b202a30a5fb16'
FROZEN_RAW_SHA='d1af2062f10f5fd25d4ac197fe74459bf0c313d7f5890f5d96c3db9572b7ddf1'
LIVE_INPUT_SHA='e6ebe5669551a2d455e7b2c036746e08e3bdd20e8e0562fab6972ab97e2a88e8'
BINDING_SHA='12ebbb79bb7bfd46e603e766d357549bf4fb381e6afe4dfdcfeaa1844d6ac6dd'
PLAN_FINGERPRINT='8aaf1f96a119e51c980a45da80031d5abd2db65d4cdc3516bd5368fd0537c7f9'

[[ "$REGISTERED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'registered SHA is invalid'
[[ -f "$CONF" && ! -L "$CONF" ]] || fail 'R3 registration is missing'
[[ "$(stat -c '%U:%G:%a' "$CONF")" == root:root:644 ]] || fail 'R3 registration metadata mismatch'
# shellcheck disable=SC1090
source "$CONF"
[[ "${audit_name:-}" == lidl-r3-promotion ]] || fail 'registration name mismatch'
[[ "${commit_sha:-}" == "$REGISTERED_SHA" ]] || fail 'requested SHA is not registered'
[[ "${apply_tool_path:-}" == "$APPLY_TOOL" ]] || fail 'registered apply path mismatch'
for item in apply_tool_sha256 plan_tool_sha256 plan_v2_tool_sha256 dispatcher_sha256; do
  [[ "${!item:-}" =~ ^[0-9a-f]{64}$ ]] || fail "invalid registered hash: $item"
done
for pair in \
  "$APPLY_TOOL:$apply_tool_sha256" \
  "$PLAN_TOOL:$plan_tool_sha256" \
  "$PLAN_V2_TOOL:$plan_v2_tool_sha256" \
  "$DISPATCHER:$dispatcher_sha256"; do
  path="${pair%%:*}"; expected="${pair##*:}"
  [[ -f "$path" && ! -L "$path" ]] || fail "registered runtime missing or unsafe: $path"
  [[ "$(stat -c '%U:%G:%a' "$path")" == root:root:755 ]] || fail "registered runtime metadata mismatch: $path"
  [[ "$(sha256sum "$path" | awk '{print $1}')" == "$expected" ]] || fail "registered runtime content drift: $path"
done
[[ -f "$AUDIT_TOOL" && ! -L "$AUDIT_TOOL" ]] || fail 'read-only semantic preflight tool is missing'
[[ "$(stat -c '%U:%G:%a' "$AUDIT_TOOL")" == root:root:755 ]] || fail 'semantic preflight tool metadata mismatch'
[[ "$(sha256sum "$AUDIT_TOOL" | awk '{print $1}')" == "$AUDIT_TOOL_SHA" ]] || fail 'semantic preflight tool content drift'

for root in "$CORPUS_ROOT" "$CORPUS_ROOT/flyers" "$FAMILY" "$PRIMARY"; do
  [[ "$(readlink -f -- "$root")" == "$root" ]] || fail "protected root path drift: $root"
  [[ -d "$root" && ! -L "$root" ]] || fail "protected root missing or unsafe: $root"
done
[[ "$(stat -c '%U:%G' "$CORPUS_ROOT")" == andris:andris ]] || fail 'corpus ownership mismatch'
[[ "$(stat -c '%U:%G:%a' "$FAMILY")" == andris:andris:700 ]] || fail 'rev05 family metadata mismatch'
[[ "$(sha256sum "$FAMILY/source.pdf" | awk '{print $1}')" == "$PDF_SHA" ]] || fail 'immutable PDF drift before promotion'
[[ "$(sha256sum "$FAMILY/source.json" | awk '{print $1}')" == "$FROZEN_RAW_SHA" ]] || fail 'immutable source JSON drift before promotion'
[[ ! -e "$PROFILE" && ! -L "$PROFILE" ]] || fail 'rev05 review-profile must be absent'
[[ ! -e "$SCAN_TARGET" && ! -L "$SCAN_TARGET" ]] || fail 'R3 scan target is already occupied'
[[ ! -e "$REFRESH_TARGET" && ! -L "$REFRESH_TARGET" ]] || fail 'R3 refresh target is already occupied'

ARTIFACT_DIR="$(readlink -f -- "$ARTIFACT_DIR")"
[[ -d "$ARTIFACT_DIR" && ! -L "$ARTIFACT_DIR" ]] || fail 'runner artifact directory missing or unsafe'
[[ "$ARTIFACT_DIR" == /home/github-runner/_work/_temp/hermes-deals-lidl-r3-promotion-* ]] || fail 'runner artifact directory outside allowlist'
[[ "$(stat -c '%U:%G:%a' "$ARTIFACT_DIR")" == github-runner:github-runner:700 ]] || fail 'runner artifact directory metadata mismatch'
KEY="$(basename -- "$ARTIFACT_DIR")"
[[ "$KEY" =~ ^hermes-deals-lidl-r3-promotion-[0-9]+-[0-9]+$ ]] || fail 'runner artifact directory name invalid'
EXPECTED_FILES=$'authorization.json\nr2.zip\nr3-plan.zip'
ACTUAL_FILES="$(find "$ARTIFACT_DIR" -mindepth 1 -maxdepth 1 -type f -printf '%f\n' | sort)"
[[ "$ACTUAL_FILES" == "$EXPECTED_FILES" ]] || fail 'runner input file set mismatch'
[[ -z "$(find "$ARTIFACT_DIR" -mindepth 1 -maxdepth 1 ! -type f -print -quit)" ]] || fail 'unexpected runner input entry'
for name in authorization.json r2.zip r3-plan.zip; do
  path="$ARTIFACT_DIR/$name"
  [[ ! -L "$path" && "$(stat -c '%U:%G:%a' "$path")" == github-runner:github-runner:600 ]] || fail "runner input metadata mismatch: $name"
done
[[ "$(sha256sum "$ARTIFACT_DIR/r2.zip" | awk '{print $1}')" == "$R2_SHA" ]] || fail 'R2 artifact ZIP SHA mismatch'
[[ "$(sha256sum "$ARTIFACT_DIR/r3-plan.zip" | awk '{print $1}')" == "$R3_SHA" ]] || fail 'R3 plan ZIP SHA mismatch'
[[ "$(stat -c '%s' "$ARTIFACT_DIR/authorization.json")" -le 8192 ]] || fail 'authorization file too large'

run_owner() { runuser -u andris -- env HOME=/home/andris PATH=/usr/local/bin:/usr/bin:/bin "$@"; }
git_read() { runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$PRIMARY" "$@"; }
file_state() {
  local path="$1"
  if [[ ! -e "$path" ]]; then printf 'missing\n'; return; fi
  [[ -f "$path" && ! -L "$path" ]] || fail "unsafe protected file: $path"
  printf '%s:%s\n' "$(stat -c '%U:%G:%a:%s' "$path")" "$(sha256sum "$path" | awk '{print $1}')"
}
outside_digest() {
  run_owner python3 - "$FAMILY" "$SCAN_TARGET" "$REFRESH_TARGET" <<'PY'
from hashlib import sha256
from pathlib import Path
import json, stat, sys
root = Path(sys.argv[1]); scan = Path(sys.argv[2]); refresh = Path(sys.argv[3])
rows=[]
for path in sorted(root.rglob('*')):
    if path == scan or scan in path.parents or path == refresh or refresh in path.parents:
        continue
    rel = path.relative_to(root)
    if rel.as_posix() in {'scans', 'source-refresh'}:
        continue
    meta=path.lstat()
    if stat.S_ISLNK(meta.st_mode): raise SystemExit(f'symlink in protected corpus: {rel}')
    if stat.S_ISDIR(meta.st_mode): rows.append([str(rel),'d',stat.S_IMODE(meta.st_mode),meta.st_uid,meta.st_gid])
    elif stat.S_ISREG(meta.st_mode):
        h=sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
        rows.append([str(rel),'f',stat.S_IMODE(meta.st_mode),meta.st_uid,meta.st_gid,meta.st_size,h.hexdigest()])
    else: raise SystemExit(f'unsupported protected corpus entry: {rel}')
print(sha256(json.dumps(rows,separators=(',',':'),ensure_ascii=True).encode()).hexdigest())
PY
}

PRIMARY_BRANCH_BEFORE="$(git_read branch --show-current)"
PRIMARY_HEAD_BEFORE="$(git_read rev-parse HEAD)"
PRIMARY_STATUS_BEFORE="$(git_read status --porcelain=v1 --untracked-files=all)"
PRIMARY_INDEX="$(git_read rev-parse --path-format=absolute --git-path index)"
PRIMARY_INDEX_BEFORE="$(file_state "$PRIMARY_INDEX")"
PRIMARY_V08_BEFORE="$(file_state "$V08_SCRIPT")"
OUTSIDE_BEFORE="$(outside_digest)"

install -d -o andris -g andris -m 0700 "$PRIVATE_ROOT"
PRIVATE="$PRIVATE_ROOT/$KEY"
[[ ! -e "$PRIVATE" ]] || fail 'private R3 evidence directory already exists'
install -d -o andris -g andris -m 0700 "$PRIVATE"
cleanup() { rm -rf -- "$PRIVATE/preflight"; }
trap cleanup EXIT
for name in authorization.json r2.zip r3-plan.zip; do
  install -o andris -g andris -m 0600 "$ARTIFACT_DIR/$name" "$PRIVATE/$name"
done

install -d -o andris -g andris -m 0700 "$PRIVATE/preflight"
run_owner python3 "$AUDIT_TOOL" --frozen-family "$FAMILY" --as-of 2026-08-08 --output-dir "$PRIVATE/preflight" \
  >"$PRIVATE/preflight.stdout" 2>"$PRIVATE/preflight.stderr" || fail 'fresh source-refresh semantic preflight failed'
LIVE_RAW="$(run_owner python3 - "$PRIVATE/preflight/source-refresh-summary.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1])); ref=p['reference_input']; live=p['live_input']; ch=p['observed_changes']
assert p['result']=='SOURCE_REFRESH_REVIEW_REQUIRED'
assert p['pdf_sha256']=='6da2135ea984d1f79bdb311dfa0d8affd1d2f8d46c63a1bba25b202a30a5fb16'
assert p['stable_source_identity_sha256']=='7486e32f837869b3dedc36b5a129c034129f653bf698df4ad55649510623ff17'
assert ref['parser_input_identity_sha256']=='8d63c989fd1897215f9556942aec16636ce7c0e5a8bb05b5a672693f58519c5a'
assert live['parser_input_identity_sha256']=='e6ebe5669551a2d455e7b2c036746e08e3bdd20e8e0562fab6972ab97e2a88e8'
assert ref['product_binding_sha256']==live['product_binding_sha256']=='12ebbb79bb7bfd46e603e766d357549bf4fb381e6afe4dfdcfeaa1844d6ac6dd'
assert ref['product_binding_count']==live['product_binding_count']==140
assert live['product_link_count']==141
assert ch=={'binding_added':0,'binding_removed':0,'binding_title_changed':0}
print(live['raw_sha256'])
PY
)" || fail 'fresh semantic identity changed after R2 review'
[[ "$LIVE_RAW" =~ ^[0-9a-f]{64}$ ]] || fail 'fresh raw provenance SHA invalid'

RESULT_FILE="$PRIVATE/r3-promotion-result.json"
set +e
run_owner python3 "$APPLY_TOOL" \
  --corpus-root "$CORPUS_ROOT" \
  --r2-artifact-zip "$PRIVATE/r2.zip" \
  --r3-plan-artifact-zip "$PRIVATE/r3-plan.zip" \
  --authorization "$PRIVATE/authorization.json" \
  --output "$RESULT_FILE" \
  >"$PRIVATE/apply.stdout" 2>"$PRIVATE/apply.stderr"
APPLY_RC=$?
set -e
[[ "$APPLY_RC" -eq 0 ]] || {
  printf 'R3_APPLY_RC=%s\n' "$APPLY_RC" >&2
  [[ ! -s "$PRIVATE/apply.stderr" ]] || head -c 1200 "$PRIVATE/apply.stderr" >&2
  fail 'R3 promotion apply failed closed'
}

run_owner python3 - "$RESULT_FILE" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
assert p['result']=='R3_PROMOTION_PASS'
assert p['plan_fingerprint']=='8aaf1f96a119e51c980a45da80031d5abd2db65d4cdc3516bd5368fd0537c7f9'
assert p['scan_tree_sha256']=='701902c873126d8bb6a6756a650b7ed46ea4a32b302742d6f3a4969f5db48e96'
assert p['source_review_sha256']=='b1563ab386fffe5ace6a3441b593596df98d0e7166bd07dff37602d9575adc09'
assert p['authority_core_sha256']=='3e1555a155dfb7f1eb16b12e837bc9fba1c38d36212616633468f58b0ee106cc'
assert p['authorization_comment_id']==5227260615
assert p['expected_gate_a_state']=='WAIT_PROFILE'
assert p['writes_performed']=={'scan_directory':True,'source_refresh_directory':True,'review_profile':False}
assert p['safety']=={
 'corpus_write_performed':True,'scan_promotion_performed':True,'source_review_promotion_performed':True,
 'authority_promotion_performed':True,'profile_promotion_performed':False,'database_write_performed':False,
 'review_write_performed':False,'auto_approve_performed':False,'auto_publish_performed':False,
 'production_deploy_performed':False,'systemd_change_performed':False,'automatic_retry_performed':False,
 'gate_c_d_authorized':False,'b15m2_v08_authorized':False}
PY

[[ "$(sha256sum "$FAMILY/source.pdf" | awk '{print $1}')" == "$PDF_SHA" ]] || fail 'immutable PDF changed'
[[ "$(sha256sum "$FAMILY/source.json" | awk '{print $1}')" == "$FROZEN_RAW_SHA" ]] || fail 'immutable source JSON changed'
[[ ! -e "$PROFILE" && ! -L "$PROFILE" ]] || fail 'rev05 review-profile appeared'
[[ -d "$SCAN_TARGET" && ! -L "$SCAN_TARGET" ]] || fail 'canonical R3 scan missing'
[[ -d "$REFRESH_TARGET" && ! -L "$REFRESH_TARGET" ]] || fail 'canonical R3 refresh authority missing'
[[ "$(outside_digest)" == "$OUTSIDE_BEFORE" ]] || fail 'corpus changed outside exact R3 targets'
[[ "$(git_read branch --show-current)" == "$PRIMARY_BRANCH_BEFORE" ]] || fail 'primary branch changed'
[[ "$(git_read rev-parse HEAD)" == "$PRIMARY_HEAD_BEFORE" ]] || fail 'primary HEAD changed'
[[ "$(git_read status --porcelain=v1 --untracked-files=all)" == "$PRIMARY_STATUS_BEFORE" ]] || fail 'primary status changed'
[[ "$(file_state "$PRIMARY_INDEX")" == "$PRIMARY_INDEX_BEFORE" ]] || fail 'primary Git index changed'
[[ "$(file_state "$V08_SCRIPT")" == "$PRIMARY_V08_BEFORE" ]] || fail 'B15M2 V08 protected state changed'

DEST="$ARTIFACT_DIR/promotion-evidence"
install -d -o github-runner -g github-runner -m 0700 "$DEST"
install -o github-runner -g github-runner -m 0600 "$RESULT_FILE" "$DEST/r3-promotion-result.json"
run_owner python3 - "$RESULT_FILE" "$LIVE_RAW" "$OUTSIDE_BEFORE" <<'PY' > "$PRIVATE/promotion-manifest.json"
import json,sys
p=json.load(open(sys.argv[1]))
print(json.dumps({
 'schema_version':1,'result':p['result'],'plan_fingerprint':p['plan_fingerprint'],
 'authorization_comment_id':p['authorization_comment_id'],
 'fresh_live_raw_sha256_provenance_only':sys.argv[2],
 'outside_target_digest_before_after':sys.argv[3],
 'expected_gate_a_state':'WAIT_PROFILE','profile_promotion_performed':False,
 'database_write_performed':False,'review_write_performed':False,
 'production_publish_performed':False,'production_deploy_performed':False,
 'systemd_change_performed':False,'automatic_retry_performed':False,
},sort_keys=True,indent=2))
PY
install -o github-runner -g github-runner -m 0600 "$PRIVATE/promotion-manifest.json" "$DEST/promotion-manifest.json"

printf 'RESULT=R3_PROMOTION_PASS\nREGISTERED_COMMIT=%s\nPLAN_FINGERPRINT=%s\n' "$REGISTERED_SHA" "$PLAN_FINGERPRINT"
printf 'FRESH_SEMANTIC_PREFLIGHT=PASS\nFRESH_RAW_SHA_PROVENANCE_ONLY=%s\n' "$LIVE_RAW"
printf 'CORPUS_WRITE=true\nSCAN_PROMOTION=true\nSOURCE_REVIEW_PROMOTION=true\nAUTHORITY_PROMOTION=true\nPROFILE_PROMOTION=false\n'
printf 'PRODUCTION_DATABASE_WRITE=false\nREVIEW_WRITE=false\nPRODUCTION_PUBLISH=false\nPRODUCTION_DEPLOY=false\nSYSTEMD_CHANGE=false\nAUTOMATIC_RETRY=false\nGATE_C_D_AUTHORIZED=false\nB15M2_V08_AUTHORIZED=false\n'
printf 'CORPUS_OUTSIDE_R3_TARGETS_UNCHANGED=true\nPRIMARY_WORKTREE_UNCHANGED=true\nPRIMARY_GIT_INDEX_UNCHANGED=true\nPRIMARY_V08_UNCHANGED=true\nEXPECTED_GATE_A_STATE=WAIT_PROFILE\n'
