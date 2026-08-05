#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

MODE="${1:-check}"
REPO='rozkalnsandris/hermes-deals'
PRIMARY_ROOT='/home/andris/hermes-deals'
RUNTIME_SYNC='/usr/local/sbin/hermes-deals-release-runtime-sync'
AUTO_REGISTER='/usr/local/sbin/hermes-deals-release-auto-register'
DISPATCH='/usr/local/sbin/hermes-deals-release-dispatch'
PUBLIC_ORIGIN='https://deals.rozkalns.net'

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ "$MODE" == check || "$MODE" == deploy ]] || fail 'usage: tools/vscode-rpi5-release.sh {check|deploy}'
for command in curl docker gh git python3 sudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
gh auth status >/dev/null 2>&1 || fail 'GitHub CLI is not authenticated'

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail 'open the Hermes Deals repository in VS Code'
ROOT="$(git rev-parse --show-toplevel)"
[[ "$ROOT" == "$PRIMARY_ROOT" ]] || fail "open the primary repository in VS Code: $PRIMARY_ROOT"
cd "$ROOT"
[[ "$(git branch --show-current)" == main ]] || fail 'deploy tasks may run only from main'
[[ -z "$(git status --porcelain --untracked-files=normal)" ]] || fail 'primary worktree is not clean'

git fetch --quiet origin main
LOCAL_SHA="$(git rev-parse HEAD)"
REMOTE_SHA="$(git rev-parse origin/main)"
[[ "$LOCAL_SHA" == "$REMOTE_SHA" ]] || fail 'local main is not synchronized with origin/main'
[[ "$REMOTE_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid current main SHA'

PR_JSON="$(gh api -H 'Accept: application/vnd.github+json' "/repos/${REPO}/commits/${REMOTE_SHA}/pulls")"
PR_NUMBER="$(python3 -c '
import json, sys
rows = json.load(sys.stdin)
valid = [row for row in rows if row.get("merged_at") and row.get("base", {}).get("ref") == "main"]
if len(valid) != 1:
    raise SystemExit(2)
print(valid[0]["number"])
' <<<"$PR_JSON")" || fail 'current main SHA is not bound to exactly one merged PR'
[[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]] || fail 'invalid source PR number'

CI_RUN_ID="$(gh api "/repos/${REPO}/actions/workflows/ci.yml/runs?branch=main&head_sha=${REMOTE_SHA}&status=completed&per_page=100" --jq '[.workflow_runs[] | select(.event == "push" and .head_branch == "main" and .head_sha == "'"$REMOTE_SHA"'" and .conclusion == "success") | .id] | max // empty')"
[[ "$CI_RUN_ID" =~ ^[1-9][0-9]*$ ]] || fail 'exact current main has no successful CI push run'

COMPOSE=(docker compose --project-directory "$ROOT" --env-file "$ROOT/.env" -f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.production.yml")
API_CONTAINER="$("${COMPOSE[@]}" ps -q api)"
DB_CONTAINER="$("${COMPOSE[@]}" ps -q db)"
[[ -n "$API_CONTAINER" && -n "$DB_CONTAINER" ]] || fail 'production API or database container is not running'
CURRENT_TAG="$(docker inspect "$API_CONTAINER" --format '{{.Config.Image}}')"
[[ "$CURRENT_TAG" == hermes-deals-api:release-* ]] || fail 'production API image is not a Hermes Deals release image'
CURRENT_REVISION="$(docker inspect "$API_CONTAINER" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
if [[ "$CURRENT_REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  PRODUCTION_SHA="$CURRENT_REVISION"
elif [[ "$CURRENT_TAG" =~ ^hermes-deals-api:release-[0-9]+\.[0-9]+\.[0-9]+-([0-9a-f]{7})$ ]]; then
  PRODUCTION_SHA="$(git rev-parse "${BASH_REMATCH[1]}^{commit}")"
else
  fail 'production API image has no valid release SHA provenance'
fi
[[ "$PRODUCTION_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid production SHA'
git merge-base --is-ancestor "$PRODUCTION_SHA" "$REMOTE_SHA" || fail 'production SHA is not an ancestor of current main'

if [[ "$PRODUCTION_SHA" == "$REMOTE_SHA" ]]; then
  printf 'NO DEPLOY NEEDED: production already runs exact current main %s.\n' "$REMOTE_SHA"
  exit 0
fi

mapfile -t CHANGED_FILES < <(git diff --name-only "${PRODUCTION_SHA}..${REMOTE_SHA}")
[[ ${#CHANGED_FILES[@]} -gt 0 ]] || fail 'release range has no changed files'
for path in "${CHANGED_FILES[@]}"; do
  case "$path" in
    docker-compose.yml|docker-compose.production.yml)
      fail 'cumulative Compose change detected; direct API/UI deploy is not authorized'
      ;;
  esac
done

mapfile -t MIGRATION_CHANGES < <(git diff --name-status "${PRODUCTION_SHA}..${REMOTE_SHA}" -- backend/alembic.ini backend/alembic/versions backend/migrations)
if (( ${#MIGRATION_CHANGES[@]} > 0 )); then
  for row in "${MIGRATION_CHANGES[@]}"; do
    status="${row%%$'\t'*}"
    path="${row#*$'\t'}"
    [[ "$status" == A && "$path" == backend/alembic/versions/*.py ]] || fail 'cumulative migration change is not an added Alembic revision'
  done
  TARGET_HEAD="$(python3 - "$ROOT/backend/alembic/versions" <<'PY'
import ast, pathlib, sys
root = pathlib.Path(sys.argv[1]); revisions=set(); parents=set()
for path in sorted(root.glob('*.py')):
    tree=ast.parse(path.read_text(encoding='utf-8'))
    values={}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {'revision','down_revision'}:
                    values[target.id]=ast.literal_eval(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in {'revision','down_revision'} and node.value is not None:
            values[node.target.id]=ast.literal_eval(node.value)
    revision=values.get('revision')
    if not revision: continue
    revisions.add(revision)
    down=values.get('down_revision')
    if isinstance(down,str): parents.add(down)
    elif isinstance(down,(tuple,list)): parents.update(down)
heads=sorted(revisions-parents)
if len(heads)!=1: raise SystemExit('target Alembic graph must have exactly one head')
print(heads[0])
PY
)"
  mapfile -d '' -t DB_FIELDS < <(docker inspect "$DB_CONTAINER" | python3 -c '
import json,sys
row=json.load(sys.stdin)[0]; env={x.partition("=")[0]:x.partition("=")[2] for x in row["Config"]["Env"] if "=" in x}
for key in ("POSTGRES_USER","POSTGRES_DB"): sys.stdout.write(env[key]+"\0")
')
  LIVE_HEAD="$("${COMPOSE[@]}" exec -T db psql -X -v ON_ERROR_STOP=1 -U "${DB_FIELDS[0]}" -d "${DB_FIELDS[1]}" -Atqc 'SELECT version_num FROM alembic_version;')"
  [[ "$LIVE_HEAD" == "$TARGET_HEAD" ]] || fail 'live schema is not already at exact target head'
fi

printf 'CHECK PASS\nPRODUCTION_SHA=%s\nTARGET_SHA=%s\nSOURCE_PR=%s\nCI_RUN_ID=%s\nCHANGED_FILES=%s\nDATABASE_WRITES_AUTHORIZED=false\n' "$PRODUCTION_SHA" "$REMOTE_SHA" "$PR_NUMBER" "$CI_RUN_ID" "${#CHANGED_FILES[@]}"
[[ "$MODE" == check ]] && exit 0

printf 'This will deploy exact current main to production.\nRequired confirmation:\n  DEPLOY api-ui %s\n' "$REMOTE_SHA"
read -r -p '> ' CONFIRMATION
[[ "$CONFIRMATION" == "DEPLOY api-ui ${REMOTE_SHA}" ]] || fail 'confirmation did not match; deployment cancelled'

sudo --non-interactive "$RUNTIME_SYNC" "$REMOTE_SHA"
sudo --non-interactive "$AUTO_REGISTER" "$REMOTE_SHA" "$PR_NUMBER" ''
EVIDENCE_ROOT="$(mktemp -d /tmp/hermes-deals-direct-release.XXXXXX)"
cleanup() { rm -rf -- "$EVIDENCE_ROOT"; }
trap cleanup EXIT
sudo --non-interactive "$DISPATCH" api-ui "$REMOTE_SHA" apply "$CI_RUN_ID" '' "$EVIDENCE_ROOT"

curl -fsS --max-time 20 "$PUBLIC_ORIGIN/api/health" >/dev/null
curl -fsSI --max-time 20 "$PUBLIC_ORIGIN/ui" >/dev/null
POST_CONTAINER="$("${COMPOSE[@]}" ps -q api)"
POST_REVISION="$(docker inspect "$POST_CONTAINER" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
[[ "$POST_REVISION" == "$REMOTE_SHA" ]] || fail 'deployed runtime SHA does not equal exact current main'

printf 'DEPLOY_RESULT=PASS\nPRODUCTION_SHA_BEFORE=%s\nPRODUCTION_SHA_AFTER=%s\nPUBLIC_API_HEALTH=PASS\nPUBLIC_UI=PASS\nDATABASE_WRITES_AUTHORIZED=false\nMIGRATION_COMMANDS_EXECUTED=false\n' "$PRODUCTION_SHA" "$POST_REVISION"
