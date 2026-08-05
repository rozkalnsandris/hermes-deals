#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

RUNNER_VERSION="edeka-shadow-cycle-v01"
RUNTIME_BOUNDARY_VERSION="edeka-shadow-cycle-index-safe-v01"
AUDIT_REPO="/home/andris/hermes-deals-audit-source"
PRIMARY_REPO="/home/andris/hermes-deals"
EVIDENCE_ROOT="/home/andris/hermes-deals-shadow-evidence/edeka"
CACHE_ROOT="/home/andris/.cache/hermes-deals-edeka-shadow"
EXPECTED_ORIGIN_HTTPS="https://github.com/rozkalnsandris/hermes-deals"
EXPECTED_ORIGIN_SSH="git@github.com:rozkalnsandris/hermes-deals.git"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

git_read_audit() {
  GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" "$@"
}

git_read_primary() {
  GIT_OPTIONAL_LOCKS=0 git -C "$PRIMARY_REPO" "$@"
}

[[ $# -eq 1 ]] || fail "usage: $0 <merged-main-commit-sha>"
EXPECTED_SHA="$1"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid expected commit SHA"
[[ "$(id -un)" == "andris" ]] || fail "run as andris, not root"

for command in awk bash cat date find flock git gzip id install mkdir mktemp mv python3 readlink rm sha256sum sort stat tar tee xargs; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

AUDIT_REPO="$(readlink -f -- "$AUDIT_REPO")"
PRIMARY_REPO="$(readlink -f -- "$PRIMARY_REPO")"
EVIDENCE_ROOT="$(readlink -m -- "$EVIDENCE_ROOT")"
CACHE_ROOT="$(readlink -m -- "$CACHE_ROOT")"

[[ "$AUDIT_REPO" == "/home/andris/hermes-deals-audit-source" ]] || fail "audit repository path drift"
[[ "$PRIMARY_REPO" == "/home/andris/hermes-deals" ]] || fail "primary repository path drift"
[[ "$EVIDENCE_ROOT" == "/home/andris/hermes-deals-shadow-evidence/edeka" ]] || fail "evidence root path drift"
[[ "$CACHE_ROOT" == "/home/andris/.cache/hermes-deals-edeka-shadow" ]] || fail "cache root path drift"

for repo in "$AUDIT_REPO" "$PRIMARY_REPO"; do
  [[ -d "$repo/.git" && ! -L "$repo/.git" ]] || fail "repository is missing or unsafe: $repo"
  [[ "$(stat -c '%U:%G' "$repo")" == "andris:andris" ]] || fail "repository ownership mismatch: $repo"
done

AUDIT_INDEX="$AUDIT_REPO/.git/index"
PRIMARY_INDEX="$PRIMARY_REPO/.git/index"
for index in "$AUDIT_INDEX" "$PRIMARY_INDEX"; do
  [[ -f "$index" && ! -L "$index" ]] || fail "repository index is missing or unsafe: $index"
  [[ "$(stat -c '%U:%G' "$index")" == "andris:andris" ]] || fail "repository index ownership mismatch: $index"
  [[ ! -e "$index.lock" ]] || fail "repository has a stale index lock: $index.lock"
done

audit_index_sha_before="$(sha256sum "$AUDIT_INDEX" | awk '{print $1}')"
audit_index_stat_before="$(stat -c '%U:%G:%a:%s:%Y' "$AUDIT_INDEX")"
primary_index_sha_before="$(sha256sum "$PRIMARY_INDEX" | awk '{print $1}')"
primary_index_stat_before="$(stat -c '%U:%G:%a:%s:%Y' "$PRIMARY_INDEX")"

audit_branch="$(git_read_audit branch --show-current)" || fail "cannot read audit repository branch"
[[ "$audit_branch" == "main" ]] || fail "audit repository branch is not main"
audit_status="$(git_read_audit status --porcelain)" || fail "cannot read audit repository status"
[[ -z "$audit_status" ]] || fail "audit repository is not clean"
audit_head="$(git_read_audit rev-parse HEAD)" || fail "cannot read audit repository HEAD"
[[ "$audit_head" == "$EXPECTED_SHA" ]] || fail "audit repository HEAD mismatch"
git_read_audit cat-file -e "$EXPECTED_SHA^{commit}" || fail "expected commit is missing"
git_read_audit merge-base --is-ancestor "$EXPECTED_SHA" main || fail "expected commit is not reachable from audit main"

origin="$(git_read_audit remote get-url origin)" || fail "cannot read audit repository origin"
case "$origin" in
  "$EXPECTED_ORIGIN_HTTPS"|"$EXPECTED_ORIGIN_HTTPS.git"|"$EXPECTED_ORIGIN_SSH") ;;
  *) fail "audit repository origin is not allowlisted" ;;
esac

for path in \
  backend/app/edeka_shadow_capture.py \
  backend/app/edeka_shadow_ledger.py \
  backend/requirements.txt \
  config/sources.json; do
  git_read_audit cat-file -e "$EXPECTED_SHA:$path" || fail "registered file is missing: $path"
done

primary_branch_before="$(git_read_primary branch --show-current)" || fail "cannot read primary repository branch"
primary_head_before="$(git_read_primary rev-parse HEAD)" || fail "cannot read primary repository HEAD"
primary_status_before="$(git_read_primary status --porcelain=v1 -z | sha256sum | awk '{print $1}')" || fail "cannot read primary repository status"

install -d -m 0700 "$EVIDENCE_ROOT" "$CACHE_ROOT"
requirements_sha="$(sha256sum "$AUDIT_REPO/backend/requirements.txt" | awk '{print $1}')"
[[ "$requirements_sha" =~ ^[0-9a-f]{64}$ ]] || fail "requirements SHA is invalid"
venv="$CACHE_ROOT/venv-$requirements_sha"
lock="$CACHE_ROOT/venv.lock"

exec 9>"$lock"
flock 9
if [[ ! -x "$venv/bin/python" ]]; then
  temporary_venv="$(mktemp -d "$CACHE_ROOT/.venv.XXXXXX")"
  cleanup_venv() {
    if [[ -n "${temporary_venv:-}" && -e "$temporary_venv" ]]; then
      rm -rf -- "$temporary_venv"
    fi
  }
  trap cleanup_venv EXIT
  python3 -m venv "$temporary_venv"
  "$temporary_venv/bin/python" -m pip install --disable-pip-version-check --upgrade pip
  "$temporary_venv/bin/python" -m pip install --disable-pip-version-check -r "$AUDIT_REPO/backend/requirements.txt"
  "$temporary_venv/bin/python" -m pip check
  mv -- "$temporary_venv" "$venv"
  temporary_venv=""
  trap - EXIT
fi
"$venv/bin/python" -m pip check >/dev/null
flock -u 9

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
run_name="${stamp}-${EXPECTED_SHA:0:12}"
run_dir="$EVIDENCE_ROOT/$run_name"
cycle_dir="$run_dir/cycle"
mkdir -m 0700 "$run_dir"

cat > "$run_dir/run-request.txt" <<REQUEST
runner_version=$RUNNER_VERSION
runtime_boundary_version=$RUNTIME_BOUNDARY_VERSION
registered_commit=$EXPECTED_SHA
audit_repository=$AUDIT_REPO
primary_repository=$PRIMARY_REPO
requirements_sha256=$requirements_sha
started_utc=$stamp
production_database_write=false
production_deployment=false
scheduler_activation=false
REQUEST

set +e
PYTHONPATH="$AUDIT_REPO/backend" \
  "$venv/bin/python" -m app.edeka_shadow_capture \
  --output-dir "$cycle_dir" \
  --sources-config "$AUDIT_REPO/config/sources.json" \
  --min-offers 150 \
  2>&1 | tee "$run_dir/capture.log"
capture_rc=${PIPESTATUS[0]}
set -e
printf '%s\n' "$capture_rc" > "$run_dir/capture-exit-code.txt"
[[ "$capture_rc" -eq 0 ]] || fail "EDEKA shadow capture failed with exit code $capture_rc"

(
  cd "$cycle_dir"
  sha256sum --check --strict SHA256SUMS
)

primary_branch_after="$(git_read_primary branch --show-current)" || fail "cannot re-read primary repository branch"
primary_head_after="$(git_read_primary rev-parse HEAD)" || fail "cannot re-read primary repository HEAD"
primary_status_after="$(git_read_primary status --porcelain=v1 -z | sha256sum | awk '{print $1}')" || fail "cannot re-read primary repository status"
[[ "$primary_branch_after" == "$primary_branch_before" ]] || fail "primary repository branch changed"
[[ "$primary_head_after" == "$primary_head_before" ]] || fail "primary repository HEAD changed"
[[ "$primary_status_after" == "$primary_status_before" ]] || fail "primary repository status changed"

audit_branch_after="$(git_read_audit branch --show-current)" || fail "cannot re-read audit repository branch"
audit_head_after="$(git_read_audit rev-parse HEAD)" || fail "cannot re-read audit repository HEAD"
audit_status_after="$(git_read_audit status --porcelain)" || fail "cannot re-read audit repository status"
[[ "$audit_branch_after" == "$audit_branch" ]] || fail "audit repository branch changed"
[[ "$audit_head_after" == "$audit_head" ]] || fail "audit repository HEAD changed"
[[ "$audit_status_after" == "$audit_status" ]] || fail "audit repository status changed"

[[ "$(sha256sum "$AUDIT_INDEX" | awk '{print $1}')" == "$audit_index_sha_before" ]] || fail "audit repository index content changed"
[[ "$(stat -c '%U:%G:%a:%s:%Y' "$AUDIT_INDEX")" == "$audit_index_stat_before" ]] || fail "audit repository index metadata changed"
[[ "$(sha256sum "$PRIMARY_INDEX" | awk '{print $1}')" == "$primary_index_sha_before" ]] || fail "primary repository index content changed"
[[ "$(stat -c '%U:%G:%a:%s:%Y' "$PRIMARY_INDEX")" == "$primary_index_stat_before" ]] || fail "primary repository index metadata changed"
[[ ! -e "$AUDIT_INDEX.lock" ]] || fail "audit repository index lock appeared"
[[ ! -e "$PRIMARY_INDEX.lock" ]] || fail "primary repository index lock appeared"

"$venv/bin/python" -m pip freeze --all | LC_ALL=C sort > "$run_dir/python-packages.txt"
printf '%s\n' "$EXPECTED_SHA" > "$run_dir/registered-commit.txt"
printf 'PRIMARY_WORKTREE_MODIFIED=false\nPRIMARY_GIT_INDEX_UNCHANGED=true\nAUDIT_GIT_INDEX_UNCHANGED=true\nPRODUCTION_DATABASE_WRITE=false\nPRODUCTION_DEPLOYMENT=false\nSCHEDULER_ACTIVATION=false\n' > "$run_dir/safety-result.txt"

(
  cd "$run_dir"
  find . -type f ! -name SHA256SUMS -print0 \
    | LC_ALL=C sort -z \
    | xargs -0 sha256sum > SHA256SUMS
  sha256sum --check --strict SHA256SUMS
)

archive="$EVIDENCE_ROOT/hermes-deals-edeka-shadow-${run_name}.tar.gz"
(
  cd "$EVIDENCE_ROOT"
  tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
    -cf - "$run_name" | gzip -n > "$archive"
)
sha256sum "$archive" > "$archive.sha256"

printf 'RESULT=PASS\n'
printf 'RUNNER_VERSION=%s\n' "$RUNNER_VERSION"
printf 'RUNTIME_BOUNDARY_VERSION=%s\n' "$RUNTIME_BOUNDARY_VERSION"
printf 'REGISTERED_COMMIT=%s\n' "$EXPECTED_SHA"
printf 'EVIDENCE_DIR=%s\n' "$run_dir"
printf 'ARCHIVE=%s\n' "$archive"
printf 'ARCHIVE_SHA256=%s\n' "$(sha256sum "$archive" | awk '{print $1}')"
printf 'PRIMARY_WORKTREE_MODIFIED=false\n'
printf 'PRIMARY_GIT_INDEX_UNCHANGED=true\n'
printf 'AUDIT_GIT_INDEX_UNCHANGED=true\n'
printf 'PRODUCTION_DATABASE_WRITE=false\n'
printf 'PRODUCTION_DEPLOYMENT=false\n'
printf 'SCHEDULER_ACTIVATION=false\n'
