#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
blocked() { printf 'BLOCKED: %s\n' "$*" >&2; exit 30; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'dispatcher must run as root through sudo'
[[ $# -eq 3 ]] || fail 'usage: dispatcher <current-main-sha> <run-id> <run-attempt>'
CURRENT_SHA="$1"
RUN_ID="$2"
RUN_ATTEMPT="$3"
[[ "$CURRENT_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'current main SHA is invalid'
[[ "$RUN_ID" =~ ^[1-9][0-9]*$ ]] || fail 'run ID must be positive'
[[ "$RUN_ATTEMPT" =~ ^[1-9][0-9]*$ ]] || fail 'run attempt must be positive'

CONF='/etc/hermes-deals-audits.d/lidl-v631-c3-readonly.conf'
AUDIT_REPO='/home/andris/hermes-deals-audit-source'
PRIMARY='/home/andris/hermes-deals'
CORPUS_ROOT='/home/andris/hermes-deals-lidl-corpus'
PRIVATE_ROOT='/var/lib/hermes-deals/lidl-v631-c3-readonly-private'
EVIDENCE_ROOT='/var/lib/hermes-deals/lidl-v631-c3-readonly'
RUNTIME_PARENT='/opt/hermes-deals-audits/lidl-v631-c3-readonly'
C3_REL='tools/lidl_v631_c3_readonly_preflight.py'
CORE_REL='backend/app/lidl_v631_c3_readonly_preflight.py'
PLANNER_REL='backend/app/lidl_v631_semantic_persistence.py'
DISPATCHER_REL='tools/runner/lidl-v631-c3-readonly-dispatcher.sh'
LOCK_REL='backend/locks/runtime-py311.txt'
MANIFEST_REL='backend/locks/manifest.json'
VERIFIER_REL='scripts/verify-python-lock-environment.py'
EXPECTED_LOCK_BLOB='d6a64564901ce38dd4a790d44ead89be917f1b21'
EXPECTED_MANIFEST_BLOB='bb0e40363afeb89a176b95bc3b9314dbef075a5d'
EXPECTED_VERIFIER_BLOB='5c7c8d5e32ef84308b688213224b2528d99378e0'

[[ -f "$CONF" && ! -L "$CONF" ]] || fail 'C3 registration is missing'
[[ "$(stat -c '%U:%G:%a' "$CONF")" == root:root:644 ]] || fail 'C3 registration metadata mismatch'
# shellcheck disable=SC1090
source "$CONF"
[[ "${audit_name:-}" == 'lidl-v631-c3-readonly' ]] || fail 'registration name mismatch'
[[ "${registered_merge_sha:-}" =~ ^[0-9a-f]{40}$ ]] || fail 'registered merge SHA invalid'
for name in c3_blob core_blob planner_blob dispatcher_blob dispatcher_sha256 runtime_lock_sha256 runtime_inventory_sha256 runtime_python_sha256; do
  value="${!name:-}"
  if [[ "$name" == dispatcher_sha256 || "$name" == runtime_lock_sha256 || "$name" == runtime_inventory_sha256 || "$name" == runtime_python_sha256 ]]; then
    [[ "$value" =~ ^[0-9a-f]{64}$ ]] || fail "$name invalid"
  else
    [[ "$value" =~ ^[0-9a-f]{40}$ ]] || fail "$name invalid"
  fi
done
RUNTIME_ROOT="$RUNTIME_PARENT/runtime-py311-${registered_merge_sha:0:12}-${runtime_lock_sha256:0:16}"
RUNTIME_PYTHON="$RUNTIME_ROOT/bin/python"
[[ "${runtime_python:-}" == "$RUNTIME_PYTHON" ]] || fail 'registered runtime Python path mismatch'
[[ "$(sha256sum /usr/local/sbin/hermes-deals-lidl-v631-c3-readonly | awk '{print $1}')" == "$dispatcher_sha256" ]] || fail 'installed dispatcher content drift'

for root in "$AUDIT_REPO" "$PRIMARY" "$CORPUS_ROOT" "$CORPUS_ROOT/flyers"; do
  [[ "$(readlink -f -- "$root")" == "$root" ]] || fail "protected root path drift: $root"
  [[ -d "$root" && ! -L "$root" ]] || fail "protected root missing or unsafe: $root"
done
for root in "$PRIVATE_ROOT" "$EVIDENCE_ROOT"; do
  [[ "$(readlink -f -- "$root")" == "$root" ]] || fail "C3 root path drift: $root"
  [[ -d "$root" && ! -L "$root" ]] || fail "C3 root missing or unsafe: $root"
done
[[ "$(stat -c '%U:%G:%a' "$PRIVATE_ROOT")" == root:root:700 ]] || fail 'private C3 root metadata mismatch'
[[ "$(stat -c '%U:%G:%a' "$EVIDENCE_ROOT")" == root:root:755 ]] || fail 'sanitized C3 evidence root metadata mismatch'
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" ]] || fail 'audit repository is missing or unsafe'
[[ "$(stat -c '%U:%G' "$AUDIT_REPO")" == andris:andris ]] || fail 'audit repository ownership mismatch'
[[ "$(stat -c '%U:%G' "$CORPUS_ROOT")" == andris:andris ]] || fail 'corpus ownership mismatch'

RUN_KEY="${RUN_ID}-${RUN_ATTEMPT}"
STAGING="$PRIVATE_ROOT/$RUN_KEY"
DEST="$EVIDENCE_ROOT/$RUN_KEY"
[[ ! -e "$STAGING" && ! -e "$DEST" ]] || fail 'C3 run key already exists'
install -d -o root -g root -m 0700 "$STAGING"
install -d -o root -g root -m 0755 "$DEST"
cleanup() { rm -rf -- "$STAGING"; }
trap cleanup EXIT

sanitize_reason_code() {
  case "${1:-}" in
    dispatcher_preflight_blocked|domain_validation|database_read_error|unexpected_internal_error|unexpected_runner_exit)
      printf '%s\n' "$1"
      ;;
    *)
      printf '%s\n' 'unexpected_internal_error'
      ;;
  esac
}

write_blocked_summary() {
  local reason_code
  local summary="$DEST/summary.json"
  reason_code="$(sanitize_reason_code "${1:-dispatcher_preflight_blocked}")"
  [[ ! -e "$summary" ]] || return 0
  python3 - "$summary" "$CURRENT_SHA" "$reason_code" <<'PY'
import json, sys
from pathlib import Path
out=Path(sys.argv[1]); sha=sys.argv[2]; reason_code=sys.argv[3]
summary={
  'schema_version':1,
  'audit':'lidl-v631-c3-readonly',
  'commit_sha':sha,
  'result':'BLOCKED',
  'reason':'preflight_blocked',
  'reason_code':reason_code,
  'safety':{
    'production_database_write':False,
    'review_write':False,
    'production_publish':False,
    'production_deploy':False,
    'corpus_write':False,
    'source_replacement':False,
    'systemd_change':False,
    'scheduler_change':False,
    'docker_exec':False,
    'container_create':False,
    'package_install':False,
  },
}
out.write_text(json.dumps(summary,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
PY
  chown root:root "$summary"
  chmod 0644 "$summary"
}

blocked() {
  printf 'BLOCKED: %s\n' "$*" >&2
  write_blocked_summary dispatcher_preflight_blocked
  exit 30
}

run_owner() { runuser -u andris -- env HOME=/home/andris PATH=/usr/local/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 "$@"; }
git_read() { runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" "$@"; }

AUDIT_BRANCH_BEFORE="$(git_read branch --show-current)"
AUDIT_HEAD_BEFORE="$(git_read rev-parse HEAD)"
AUDIT_STATUS_BEFORE="$(git_read status --porcelain=v1 --untracked-files=all)"
[[ "$AUDIT_BRANCH_BEFORE" == main ]] || fail 'audit clone is not on main'
[[ "$AUDIT_HEAD_BEFORE" == "$CURRENT_SHA" ]] || blocked 'audit clone is not at current authorized main SHA'
[[ -z "$AUDIT_STATUS_BEFORE" ]] || blocked 'audit clone is not clean'
git_read merge-base --is-ancestor "$registered_merge_sha" "$CURRENT_SHA" || fail 'registered C3 bridge merge is not reachable from current audit main'
INDEX="$(git_read rev-parse --path-format=absolute --git-path index)"
[[ -f "$INDEX" && ! -L "$INDEX" ]] || fail 'audit Git index is missing or unsafe'
[[ ! -e "$INDEX.lock" ]] || fail 'audit Git index lock exists'
INDEX_SHA_BEFORE="$(sha256sum "$INDEX" | awk '{print $1}')"
INDEX_STAT_BEFORE="$(stat -c '%U:%G:%a:%s:%Y' "$INDEX")"

for spec in \
  "$C3_REL:$c3_blob" \
  "$CORE_REL:$core_blob" \
  "$PLANNER_REL:$planner_blob" \
  "$DISPATCHER_REL:$dispatcher_blob" \
  "$LOCK_REL:$EXPECTED_LOCK_BLOB" \
  "$MANIFEST_REL:$EXPECTED_MANIFEST_BLOB" \
  "$VERIFIER_REL:$EXPECTED_VERIFIER_BLOB"; do
  path="${spec%%:*}"
  expected="${spec##*:}"
  actual="$(git_read rev-parse "$CURRENT_SHA:$path")"
  [[ "$actual" == "$expected" ]] || fail "current main C3 blob drift: $path"
done

[[ -d "$RUNTIME_ROOT" && ! -L "$RUNTIME_ROOT" ]] || blocked 'pinned C3 audit runtime missing or unsafe'
[[ "$(readlink -f -- "$RUNTIME_ROOT")" == "$RUNTIME_ROOT" ]] || fail 'pinned C3 runtime path drift'
[[ -f "$RUNTIME_PYTHON" && ! -L "$RUNTIME_PYTHON" && -x "$RUNTIME_PYTHON" ]] || blocked 'pinned C3 audit Python missing or unsafe'
[[ "$(sha256sum "$RUNTIME_PYTHON" | awk '{print $1}')" == "$runtime_python_sha256" ]] || blocked 'pinned C3 runtime interpreter drift'
if find "$RUNTIME_ROOT" -xdev \( ! -user root -o ! -group root \) -print -quit | grep -q .; then
  fail 'pinned C3 runtime ownership is unsafe'
fi
if find "$RUNTIME_ROOT" -xdev \( -type f -o -type d \) -perm /022 -print -quit | grep -q .; then
  fail 'pinned C3 runtime write permissions are unsafe'
fi
RUNTIME_PYTHON_VERSION="$(run_owner "$RUNTIME_PYTHON" - "$RUNTIME_ROOT" <<'PY'
import sys
expected=sys.argv[1]
version=f"{sys.version_info.major}.{sys.version_info.minor}"
if version != '3.11': raise SystemExit(f'unexpected runtime Python: {version}')
if sys.prefix != expected: raise SystemExit('runtime sys.prefix mismatch')
if sys.base_prefix == sys.prefix: raise SystemExit('runtime is not isolated')
print(version)
PY
)" || blocked 'pinned C3 runtime interpreter identity failed'
[[ "$RUNTIME_PYTHON_VERSION" == 3.11 ]] || blocked 'pinned C3 runtime Python version mismatch'
[[ "$(sha256sum "$AUDIT_REPO/$LOCK_REL" | awk '{print $1}')" == "$runtime_lock_sha256" ]] || fail 'registered runtime lock SHA mismatch'
MANIFEST_LOCK_SHA="$(python3 - "$AUDIT_REPO/$MANIFEST_REL" <<'PY'
import json, sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
row=obj.get('locks',{}).get('runtime-py311.txt') or {}
if row.get('python')!='3.11': raise SystemExit('runtime manifest Python mismatch')
print(row.get('sha256') or '')
PY
)"
[[ "$MANIFEST_LOCK_SHA" == "$runtime_lock_sha256" ]] || fail 'runtime manifest lock identity mismatch'
ENVIRONMENT_REPORT="$(run_owner "$RUNTIME_PYTHON" "$AUDIT_REPO/$VERIFIER_REL" "$AUDIT_REPO/$LOCK_REL")" || blocked 'pinned C3 audit runtime verification failed'
INVENTORY_SHA="$(printf '%s\n' "$ENVIRONMENT_REPORT" | awk -F= '$1 == "LOCKED_INVENTORY_SHA256" {print $2}')"
[[ "$INVENTORY_SHA" == "$runtime_inventory_sha256" ]] || blocked 'pinned C3 audit runtime inventory drift'
for module in sqlalchemy psycopg pydantic; do
  run_owner "$RUNTIME_PYTHON" -c "import $module" >/dev/null 2>&1 || blocked "pinned C3 runtime dependency unavailable: $module"
done
command -v docker >/dev/null 2>&1 || blocked 'docker CLI unavailable'

corpus_tree() {
  run_owner python3 - "$CORPUS_ROOT" <<'PY'
from hashlib import sha256
from pathlib import Path
import json, stat, sys
root = Path(sys.argv[1])
rows=[]
for path in sorted(root.rglob('*')):
    meta=path.lstat(); rel=str(path.relative_to(root))
    if stat.S_ISLNK(meta.st_mode): raise SystemExit(f'symlink in corpus: {rel}')
    if stat.S_ISDIR(meta.st_mode): rows.append([rel,'d',stat.S_IMODE(meta.st_mode),meta.st_uid,meta.st_gid])
    elif stat.S_ISREG(meta.st_mode):
        h=sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
        rows.append([rel,'f',stat.S_IMODE(meta.st_mode),meta.st_uid,meta.st_gid,meta.st_size,h.hexdigest()])
    else: raise SystemExit(f'unsupported corpus entry: {rel}')
print(sha256(json.dumps(rows,separators=(',',':'),ensure_ascii=True).encode()).hexdigest())
PY
}
CORPUS_BEFORE="$(corpus_tree)"
[[ "$CORPUS_BEFORE" =~ ^[0-9a-f]{64}$ ]] || fail 'corpus baseline digest invalid'

mapfile -t DB_IDS < <(docker ps --filter 'label=com.docker.compose.project=hermes-deals' --filter 'label=com.docker.compose.service=db' --format '{{.ID}}')
[[ ${#DB_IDS[@]} -eq 1 ]] || blocked 'expected exactly one running hermes-deals production db container'
DB_ID="${DB_IDS[0]}"
INSPECT="$STAGING/db-inspect.json"
[[ ! -e "$INSPECT" ]] || fail 'private inspect path already exists'
docker inspect "$DB_ID" > "$INSPECT"
chmod 0600 "$INSPECT"
[[ "$(stat -c '%U:%G:%a' "$INSPECT")" == root:root:600 ]] || fail 'private inspect metadata mismatch'

DATABASE_URL="$(python3 - "$INSPECT" <<'PY'
import json, sys
from urllib.parse import quote
obj=json.load(open(sys.argv[1], encoding='utf-8'))[0]
state=obj.get('State') or {}; health=state.get('Health') or {}
if state.get('Running') is not True or health.get('Status') != 'healthy': raise SystemExit('db container is not running+healthy')
if str((obj.get('Config') or {}).get('Image') or '') != 'postgres:18.4-bookworm': raise SystemExit('db image identity mismatch')
env={}
for row in (obj.get('Config') or {}).get('Env') or []:
    if '=' in row:
        k,v=row.split('=',1); env[k]=v
for key in ('POSTGRES_USER','POSTGRES_PASSWORD','POSTGRES_DB'):
    if not env.get(key): raise SystemExit(f'missing {key}')
networks=(obj.get('NetworkSettings') or {}).get('Networks') or {}
ips=[str(v.get('IPAddress') or '') for k,v in networks.items() if k.endswith('_internal') and v.get('IPAddress')]
if len(ips) != 1: raise SystemExit('production db internal network identity is ambiguous')
print('postgresql+psycopg://%s:%s@%s:5432/%s' % (quote(env['POSTGRES_USER'],safe=''),quote(env['POSTGRES_PASSWORD'],safe=''),ips[0],quote(env['POSTGRES_DB'],safe='')))
PY
)" || blocked 'could not derive production DB read-only connection target'
[[ "$DATABASE_URL" == postgresql+psycopg://* ]] || fail 'derived DATABASE_URL shape invalid'
rm -f -- "$INSPECT"

RUN_LOG="$STAGING/c3.log"
[[ ! -e "$RUN_LOG" ]] || fail 'private C3 log path already exists'
set +e
runuser -u andris -- env HOME=/home/andris PATH=/usr/local/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 DATABASE_URL="$DATABASE_URL" \
  "$RUNTIME_PYTHON" "$AUDIT_REPO/$C3_REL" --expected-head "$CURRENT_SHA" --corpus-root "$CORPUS_ROOT" >"$RUN_LOG" 2>&1
RC=$?
set -e
unset DATABASE_URL

REASON_CODE=''
if [[ "$RC" -eq 30 ]]; then
  mapfile -t BLOCKED_CODES < <(grep -E '^BLOCKED_CODE=(domain_validation|database_read_error|unexpected_internal_error)$' "$RUN_LOG" || true)
  if [[ ${#BLOCKED_CODES[@]} -eq 1 ]]; then
    REASON_CODE="${BLOCKED_CODES[0]#BLOCKED_CODE=}"
  else
    REASON_CODE='unexpected_internal_error'
  fi
elif [[ "$RC" -ne 0 ]]; then
  REASON_CODE='unexpected_runner_exit'
  RC=30
fi

CORPUS_AFTER="$(corpus_tree)"
[[ "$CORPUS_AFTER" == "$CORPUS_BEFORE" ]] || fail 'authoritative corpus changed during C3 read-only preflight'
[[ "$(git_read branch --show-current)" == "$AUDIT_BRANCH_BEFORE" ]] || fail 'audit branch changed'
[[ "$(git_read rev-parse HEAD)" == "$AUDIT_HEAD_BEFORE" ]] || fail 'audit HEAD changed'
[[ "$(git_read status --porcelain=v1 --untracked-files=all)" == "$AUDIT_STATUS_BEFORE" ]] || fail 'audit worktree status changed'
[[ "$(sha256sum "$INDEX" | awk '{print $1}')" == "$INDEX_SHA_BEFORE" ]] || fail 'audit Git index changed'
[[ "$(stat -c '%U:%G:%a:%s:%Y' "$INDEX")" == "$INDEX_STAT_BEFORE" ]] || fail 'audit Git index metadata changed'
[[ ! -e "$INDEX.lock" ]] || fail 'audit Git index lock appeared'

SUMMARY="$DEST/summary.json"
[[ ! -e "$SUMMARY" ]] || fail 'sanitized summary already exists'
python3 - "$RUN_LOG" "$SUMMARY" "$CURRENT_SHA" "$RC" "$REASON_CODE" "$CORPUS_BEFORE" "$runtime_lock_sha256" "$runtime_inventory_sha256" "$runtime_python_sha256" "$RUNTIME_PYTHON_VERSION" <<'PY'
import json, re, sys
from pathlib import Path
log, out, sha, rc, reason_code, corpus, lock_sha, inventory_sha, python_sha, python_version = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]), sys.argv[5], sys.argv[6], sys.argv[7], sys.argv[8], sys.argv[9], sys.argv[10]
allowed_reason_codes={'domain_validation','database_read_error','unexpected_internal_error','unexpected_runner_exit'}
summary={
 'schema_version':1,'audit':'lidl-v631-c3-readonly','commit_sha':sha,
 'result':'BLOCKED' if rc==30 else 'PASS','reason':'runner_failed_closed' if rc==30 else 'validated_read_only_write_plan',
 'corpus_tree_sha256':corpus,'runtime_lock_sha256':lock_sha,'runtime_inventory_sha256':inventory_sha,'runtime_python_sha256':python_sha,'runtime_python_version':python_version,
 'safety':{'production_database_write':False,'review_write':False,'production_publish':False,'production_deploy':False,'corpus_write':False,'source_replacement':False,'systemd_change':False,'scheduler_change':False,'docker_exec':False,'container_create':False,'package_install':False}
}
if rc==30:
    if reason_code not in allowed_reason_codes: raise SystemExit('sanitized BLOCKED reason code invalid')
    summary['reason_code']=reason_code
else:
    lines=log.read_text(encoding='utf-8', errors='replace').splitlines()
    report=None
    for line in lines:
        if line.startswith('{'):
            try: report=json.loads(line)
            except json.JSONDecodeError: pass
    if not isinstance(report,dict) or report.get('result')!='C3_READ_ONLY_PASS': raise SystemExit('C3 report missing or invalid')
    tx=report.get('transaction') or {}
    if tx!={'transaction_read_only':'on','transaction_isolation':'repeatable read'}: raise SystemExit('transaction safety mismatch')
    if report.get('production_baseline_before') != report.get('production_baseline_after'): raise SystemExit('baseline changed')
    if report.get('exact_key_counts') != {'snapshot_id':0,'snapshot_raw_sha256':0,'offer_uniqueness_key':0}: raise SystemExit('exact production key already exists')
    if report.get('expected_first_apply_delta') != {'source_snapshots':1,'offer_candidates':1}: raise SystemExit('expected delta mismatch')
    if report.get('rollback_only') is not True or report.get('transaction_rolled_back') is not True: raise SystemExit('rollback proof missing')
    for key in ('database_write','review_write','production_publish','production_deploy','corpus_write','source_replacement','systemd_change','scheduler_change'):
        if report.get(key) is not False: raise SystemExit(f'unsafe report flag: {key}')
    for key in ('plan_fingerprint','payload_fingerprint'):
        if re.fullmatch(r'[0-9a-f]{64}',str(report.get(key) or '')) is None: raise SystemExit(f'invalid {key}')
    summary.update({
      'plan_result':report.get('plan_result'),'plan_fingerprint':report.get('plan_fingerprint'),'payload_fingerprint':report.get('payload_fingerprint'),
      'production_baseline':report.get('production_baseline_before'),'exact_key_counts':report.get('exact_key_counts'),
      'source_snapshot_id':report.get('source_snapshot_id'),'source_offer_id':report.get('source_offer_id'),'expected_first_apply_delta':report.get('expected_first_apply_delta'),
      'transaction':tx,'transaction_rolled_back':True,
    })
out.write_text(json.dumps(summary,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
PY
chown root:root "$SUMMARY"
chmod 0644 "$SUMMARY"
[[ "$(stat -c '%U:%G:%a' "$SUMMARY")" == root:root:644 ]] || fail 'sanitized summary metadata mismatch'

if [[ "$RC" -eq 30 ]]; then
  exit 30
fi
printf 'C3_DISPATCH_RESULT=PASS\n'
printf 'RUNTIME_LOCK_SHA256=%s\nRUNTIME_INVENTORY_SHA256=%s\nRUNTIME_PYTHON_SHA256=%s\nRUNTIME_PYTHON_VERSION=%s\n' "$runtime_lock_sha256" "$runtime_inventory_sha256" "$runtime_python_sha256" "$RUNTIME_PYTHON_VERSION"
printf 'PRODUCTION_DATABASE_WRITE=false\nCORPUS_WRITE=false\nREVIEW_WRITE=false\nPRODUCTION_PUBLISH=false\nPRODUCTION_DEPLOY=false\nSYSTEMD_CHANGE=false\nSCHEDULER_CHANGE=false\nPACKAGE_INSTALL=false\n'
