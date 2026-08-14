#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

MODE="${1:-check}"
REPO='rozkalnsandris/hermes-deals'
PRIMARY_ROOT='/home/andris/hermes-deals'
RUNTIME_SYNC='/usr/local/sbin/hermes-deals-release-runtime-sync'
MAIN_DEPLOY='/usr/local/sbin/hermes-deals-release-main-deploy'

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

for command in curl docker gh git python3 sudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
gh auth status >/dev/null 2>&1 || fail 'GitHub CLI is not authenticated; run: gh auth login'

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail 'open the Hermes Deals repository in VS Code'
ROOT="$(git rev-parse --show-toplevel)"
[[ "$ROOT" == "$PRIMARY_ROOT" ]] || fail "open the primary repository in VS Code: $PRIMARY_ROOT"
cd "$ROOT"

BRANCH="$(git branch --show-current)"
[[ "$BRANCH" == main ]] || fail "deploy tasks may run only from main (current: ${BRANCH:-detached})"
[[ -z "$(git status --porcelain --untracked-files=normal)" ]] \
  || fail 'the primary worktree is not clean'

printf 'Fetching origin/main...\n'
git fetch --quiet origin main
LOCAL_SHA="$(git rev-parse HEAD)"
REMOTE_SHA="$(git rev-parse origin/main)"
[[ "$LOCAL_SHA" == "$REMOTE_SHA" ]] \
  || fail 'local main is not synchronized with origin/main; fast-forward it first'
[[ "$REMOTE_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid main SHA'

CI_JSON="$(gh api \
  "/repos/${REPO}/actions/workflows/ci.yml/runs?branch=main&event=push&status=completed&per_page=100")"
CI_RUN_ID="$(python3 -c '
import json
import sys

sha = sys.argv[1]
rows = json.load(sys.stdin).get("workflow_runs", [])
matches = [
    row for row in rows
    if row.get("event") == "push"
    and row.get("head_branch") == "main"
    and row.get("head_sha") == sha
    and row.get("conclusion") == "success"
]
if not matches:
    raise SystemExit(2)
print(max(int(row["id"]) for row in matches))
' "$REMOTE_SHA" <<<"$CI_JSON")" || fail 'exact current main has no successful CI push run'
[[ "$CI_RUN_ID" =~ ^[1-9][0-9]*$ ]] || fail 'invalid exact-main CI run ID'

COMPOSE=(
  docker compose
  --project-directory "$ROOT"
  --env-file "$ROOT/.env"
  -f "$ROOT/docker-compose.yml"
  -f "$ROOT/docker-compose.production.yml"
)

read_live_alembic() {
  local db_container db_user db_name
  local -a fields
  db_container="$("${COMPOSE[@]}" ps -q db)"
  [[ -n "$db_container" ]] || fail 'production database container is not running'
  mapfile -d '' -t fields < <(docker inspect "$db_container" | python3 -c '
import json
import sys
rows = json.load(sys.stdin)
if len(rows) != 1:
    raise SystemExit(2)
env = {}
for item in rows[0].get("Config", {}).get("Env", []):
    key, sep, value = item.partition("=")
    if sep:
        env[key] = value
for key in ("POSTGRES_USER", "POSTGRES_DB"):
    value = env.get(key, "")
    if not value or "\x00" in value:
        raise SystemExit(2)
    sys.stdout.write(value + "\x00")
')
  [[ ${#fields[@]} -eq 2 ]] || fail 'production database identity could not be resolved'
  db_user="${fields[0]}"
  db_name="${fields[1]}"
  "${COMPOSE[@]}" exec -T db \
    psql -X -v ON_ERROR_STOP=1 -U "$db_user" -d "$db_name" -Atqc \
    'SELECT version_num FROM alembic_version;'
}

CURRENT_CONTAINER="$("${COMPOSE[@]}" ps -q api)"
[[ -n "$CURRENT_CONTAINER" ]] || fail 'production API container is not running'
CURRENT_TAG="$(docker inspect "$CURRENT_CONTAINER" --format '{{.Config.Image}}')"
CURRENT_REVISION="$(docker inspect "$CURRENT_CONTAINER" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')"
MANAGED_TAG_SHA=''
if [[ "$CURRENT_TAG" =~ ^hermes-deals-api:(main|w4b|w4c)-([0-9a-f]{12})$ ]]; then
  MANAGED_TAG_SHA="${BASH_REMATCH[2]}"
  [[ "$CURRENT_REVISION" =~ ^[0-9a-f]{40}$ ]] \
    || fail 'managed production image requires an exact OCI revision label'
  [[ "$MANAGED_TAG_SHA" == "${CURRENT_REVISION:0:12}" ]] \
    || fail 'managed production image tag does not match OCI revision'
elif [[ "$CURRENT_TAG" =~ ^hermes-deals-api:release-[A-Za-z0-9_.-]+$ ]]; then
  :
else
  fail 'production API image is not a managed Hermes Deals release image'
fi
PRODUCTION_REF=''
PRODUCTION_PROVENANCE=''
if [[ "$CURRENT_REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  PRODUCTION_REF="$CURRENT_REVISION"
  PRODUCTION_PROVENANCE='oci-revision'
elif [[ -n "$CURRENT_REVISION" && "$CURRENT_REVISION" != '<no value>' ]]; then
  fail 'production API image has malformed OCI revision label'
elif [[ "$CURRENT_TAG" =~ ^hermes-deals-api:release-[0-9]+\.[0-9]+\.[0-9]+-([0-9a-f]{7})$ ]]; then
  PRODUCTION_REF="${BASH_REMATCH[1]}"
  PRODUCTION_PROVENANCE='canonical-tag'
else
  fail 'production API image has no valid release SHA provenance'
fi
PRODUCTION_SHA="$(git rev-parse "${PRODUCTION_REF}^{commit}" 2>/dev/null)" \
  || fail 'production release SHA cannot be resolved from Git history'
[[ "$PRODUCTION_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid production SHA'
if [[ "$PRODUCTION_PROVENANCE" == oci-revision && "$PRODUCTION_SHA" != "$CURRENT_REVISION" ]]; then
  fail 'production OCI revision contradicts resolved Git commit'
fi
git merge-base --is-ancestor "$PRODUCTION_SHA" "$REMOTE_SHA" \
  || fail 'running production SHA is not an ancestor of current main'

COMMIT_COUNT="$(git rev-list --count "${PRODUCTION_SHA}..${REMOTE_SHA}")"
[[ "$COMMIT_COUNT" =~ ^[0-9]+$ ]] || fail 'invalid cumulative commit count'
PRE_ALEMBIC="$(read_live_alembic)"

if [[ "$COMMIT_COUNT" == 0 ]]; then
  printf '\nNO DEPLOY NEEDED\n'
  printf 'PRODUCTION_SHA=%s\n' "$PRODUCTION_SHA"
  printf 'TARGET_SHA=%s\n' "$REMOTE_SHA"
  printf 'CI_RUN_ID=%s\n' "$CI_RUN_ID"
  printf 'ALEMBIC_HEAD=%s\n' "$PRE_ALEMBIC"
  exit 0
fi

mapfile -t CHANGED_FILES < <(git diff --name-only "${PRODUCTION_SHA}..${REMOTE_SHA}")
[[ ${#CHANGED_FILES[@]} -gt 0 ]] || fail 'cumulative release range has no changed files'

for path in "${CHANGED_FILES[@]}"; do
  case "$path" in
    docker-compose.yml|docker-compose.production.yml)
      fail 'cumulative Compose change detected; direct API/UI deploy is not authorized'
      ;;
  esac
done

MIGRATION_RECONCILIATION='not-required'
mapfile -t MIGRATION_CHANGES < <(
  git diff --name-status "${PRODUCTION_SHA}..${REMOTE_SHA}" -- \
    backend/alembic.ini backend/alembic/versions backend/migrations
)
if (( ${#MIGRATION_CHANGES[@]} > 0 )); then
  for row in "${MIGRATION_CHANGES[@]}"; do
    status="${row%%$'\t'*}"
    path="${row#*$'\t'}"
    [[ "$status" == A && "$path" == backend/alembic/versions/*.py ]] \
      || fail 'cumulative database migration change is not an added Alembic revision'
  done

  TARGET_ALEMBIC_HEAD="$(python3 - "$ROOT/backend/alembic/versions" <<'PY'
import ast
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
revisions = set()
parents = set()
for path in sorted(root.glob("*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                    values[target.id] = ast.literal_eval(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in {"revision", "down_revision"} and node.value is not None:
                values[node.target.id] = ast.literal_eval(node.value)
    revision = values.get("revision")
    if revision is None:
        continue
    if not isinstance(revision, str) or not revision or revision in revisions:
        raise SystemExit(2)
    revisions.add(revision)
    down = values.get("down_revision")
    if isinstance(down, str):
        parents.add(down)
    elif isinstance(down, (tuple, list)):
        if not all(isinstance(item, str) and item for item in down):
            raise SystemExit(2)
        parents.update(down)
    elif down is not None:
        raise SystemExit(2)
heads = sorted(revisions - parents)
if len(heads) != 1:
    raise SystemExit(2)
print(heads[0])
PY
)" || fail 'target Alembic head could not be resolved'
  [[ "$PRE_ALEMBIC" == "$TARGET_ALEMBIC_HEAD" ]] \
    || fail 'live schema is not already at exact target Alembic head'
  MIGRATION_RECONCILIATION="verified-live-head:${PRE_ALEMBIC}"
fi

printf '\nHermes Deals direct main release candidate\n'
printf '  production tag:  %s\n' "$CURRENT_TAG"
printf '  provenance:      %s\n' "$PRODUCTION_PROVENANCE"
printf '  production SHA:  %s\n' "$PRODUCTION_SHA"
printf '  target main SHA: %s\n' "$REMOTE_SHA"
printf '  exact-main CI:   %s\n' "$CI_RUN_ID"
printf '  commits:         %s\n' "$COMMIT_COUNT"
printf '  changed files:   %s\n' "${#CHANGED_FILES[@]}"
printf '  schema gate:     %s\n' "$MIGRATION_RECONCILIATION"

case "$MODE" in
  check)
    printf '\nCHECK PASS\n'
    printf 'TARGET_SHA=%s\n' "$REMOTE_SHA"
    printf 'CI_RUN_ID=%s\n' "$CI_RUN_ID"
    printf 'DATABASE_WRITES_AUTHORIZED=false\n'
    printf 'PRODUCTION_CHANGED=false\n'
    ;;

  deploy)
    [[ -x "$RUNTIME_SYNC" && ! -L "$RUNTIME_SYNC" ]] \
      || fail 'guarded runtime-sync helper is missing or unsafe'
    printf '\nSynchronizing guarded release runtime...\n'
    SYNC_OUTPUT="$(sudo --non-interactive "$RUNTIME_SYNC" "$REMOTE_SHA")"
    printf '%s\n' "$SYNC_OUTPUT"
    grep -Fq 'RUNTIME_SYNC_RESULT=PASS' <<<"$SYNC_OUTPUT" \
      || fail 'runtime sync did not return PASS'
    grep -Fq "SOURCE_SHA=$REMOTE_SHA" <<<"$SYNC_OUTPUT" \
      || fail 'runtime sync SHA mismatch'
    grep -Fq 'PRODUCTION_CHANGED=false' <<<"$SYNC_OUTPUT" \
      || fail 'runtime sync did not prove production stability'

    [[ -x "$MAIN_DEPLOY" && ! -L "$MAIN_DEPLOY" ]] \
      || fail 'guarded direct-main deploy helper is missing or unsafe'
    printf '\nDeploying exact current main...\n'
    DEPLOY_OUTPUT="$(sudo --non-interactive "$MAIN_DEPLOY" "$REMOTE_SHA")"
    printf '%s\n' "$DEPLOY_OUTPUT"
    grep -Fq 'MAIN_DEPLOY_RESULT=PASS' <<<"$DEPLOY_OUTPUT" \
      || fail 'direct-main deploy did not return PASS'
    grep -Fq "SOURCE_SHA=$REMOTE_SHA" <<<"$DEPLOY_OUTPUT" \
      || fail 'direct-main deploy SHA mismatch'
    grep -Fq 'DATABASE_WRITES_AUTHORIZED=false' <<<"$DEPLOY_OUTPUT" \
      || fail 'deploy did not preserve the database-write boundary'

    AFTER_CONTAINER="$("${COMPOSE[@]}" ps -q api)"
    [[ -n "$AFTER_CONTAINER" ]] || fail 'production API container is missing after deploy'
    AFTER_REVISION="$(docker inspect "$AFTER_CONTAINER" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')"
    [[ "$AFTER_REVISION" == "$REMOTE_SHA" ]] \
      || fail 'production API revision is not exact current main after deploy'
    POST_ALEMBIC="$(read_live_alembic)"
    [[ "$POST_ALEMBIC" == "$PRE_ALEMBIC" ]] \
      || fail 'live Alembic revision changed during API/UI deploy'
    curl --fail --silent --show-error --max-time 20 \
      https://deals.rozkalns.net/api/health >/dev/null
    curl --fail --silent --show-error --head --max-time 20 \
      https://deals.rozkalns.net/ui >/dev/null

    printf '\nDEPLOY PASS\n'
    printf 'SOURCE_SHA=%s\n' "$REMOTE_SHA"
    printf 'PRODUCTION_SHA=%s\n' "$AFTER_REVISION"
    printf 'CI_RUN_ID=%s\n' "$CI_RUN_ID"
    printf 'ALEMBIC_BEFORE=%s\n' "$PRE_ALEMBIC"
    printf 'ALEMBIC_AFTER=%s\n' "$POST_ALEMBIC"
    printf 'PUBLIC_API_HEALTH=PASS\n'
    printf 'PUBLIC_UI=PASS\n'
    printf 'MIGRATION_COMMANDS_EXECUTED=false\n'
    printf 'DATABASE_WRITES_AUTHORIZED=false\n'
    printf 'ROLLBACK_PERFORMED=false\n'
    ;;

  *)
    fail "usage: $0 {check|deploy}"
    ;;
esac
