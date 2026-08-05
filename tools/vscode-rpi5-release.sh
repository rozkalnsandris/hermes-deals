#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

MODE="${1:-check}"
REPO="rozkalnsandris/hermes-deals"
PRIMARY_ROOT="/home/andris/hermes-deals"
BRIDGE_MARKER="<!-- hermes-deals-release-request-v1 -->"
DEPLOY_LABEL="hermes:deploy-ready"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

for command in docker gh git python3 sudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
gh auth status >/dev/null 2>&1 || fail "GitHub CLI is not authenticated; run: gh auth login"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "open the Hermes Deals repository in VS Code"
ROOT="$(git rev-parse --show-toplevel)"
[[ "$ROOT" == "$PRIMARY_ROOT" ]] || fail "open the primary repository in VS Code: $PRIMARY_ROOT"
cd "$ROOT"

BRANCH="$(git branch --show-current)"
[[ "$BRANCH" == "main" ]] || fail "deploy tasks may run only from the main branch (current: ${BRANCH:-detached})"
[[ -z "$(git status --porcelain --untracked-files=normal)" ]] \
  || fail "the RPi5 primary worktree is not clean; commit, move, or remove local changes first"

printf 'Fetching origin/main...\n'
git fetch --quiet origin main
LOCAL_SHA="$(git rev-parse HEAD)"
REMOTE_SHA="$(git rev-parse origin/main)"
[[ "$LOCAL_SHA" == "$REMOTE_SHA" ]] \
  || fail "local main is not synchronized with origin/main; use fast-forward pull before release"
[[ "$REMOTE_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid main SHA"

PR_JSON="$(gh api -H 'Accept: application/vnd.github+json' "/repos/${REPO}/commits/${REMOTE_SHA}/pulls")"
PR_NUMBER="$(python3 -c '
import json, sys
items = json.load(sys.stdin)
valid = [p for p in items if p.get("merged_at") and p.get("base", {}).get("ref") == "main"]
if len(valid) != 1:
    raise SystemExit(2)
print(valid[0]["number"])
' <<<"$PR_JSON")" || fail "current main SHA is not bound to exactly one merged PR"

PR_DETAIL="$(gh api "/repos/${REPO}/pulls/${PR_NUMBER}")"
PR_TITLE="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["title"])' <<<"$PR_DETAIL")"
SOURCE_ISSUE="$(python3 -c '
import json, re, sys
body = str(json.load(sys.stdin).get("body") or "")
values = sorted(set(int(value) for value in re.findall(r"(?im)^\s*(?:closes|fixes|resolves)\s+#([0-9]+)\b", body)))
if len(values) != 1:
    raise SystemExit(2)
print(values[0])
' <<<"$PR_DETAIL")" || fail "current main PR must close exactly one source issue"
[[ "$SOURCE_ISSUE" != "20" ]] || fail "B15M2 issue #20 is excluded from the API/UI release bridge"

COMPOSE=(
  docker compose
  --project-directory "$ROOT"
  --env-file "$ROOT/.env"
  -f "$ROOT/docker-compose.yml"
  -f "$ROOT/docker-compose.production.yml"
)
CURRENT_CONTAINER="$("${COMPOSE[@]}" ps -q api)"
[[ -n "$CURRENT_CONTAINER" ]] || fail "production API container is not running"
CURRENT_TAG="$(docker inspect "$CURRENT_CONTAINER" --format '{{.Config.Image}}')"
[[ "$CURRENT_TAG" == hermes-deals-api:release-* ]] \
  || fail "production API image is not a Hermes Deals release image"
CURRENT_REVISION="$(docker inspect "$CURRENT_CONTAINER" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')"
PRODUCTION_REF=""
PRODUCTION_PROVENANCE=""
if [[ "$CURRENT_REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  PRODUCTION_REF="$CURRENT_REVISION"
  PRODUCTION_PROVENANCE="oci-revision"
elif [[ -n "$CURRENT_REVISION" && "$CURRENT_REVISION" != "<no value>" ]]; then
  fail "production API image has malformed OCI revision label"
elif [[ "$CURRENT_TAG" =~ ^hermes-deals-api:release-[0-9]+\.[0-9]+\.[0-9]+-([0-9a-f]{7})$ ]]; then
  PRODUCTION_REF="${BASH_REMATCH[1]}"
  PRODUCTION_PROVENANCE="canonical-tag"
else
  fail "production API image has no valid release SHA provenance"
fi
PRODUCTION_SHA="$(git rev-parse "${PRODUCTION_REF}^{commit}" 2>/dev/null)" \
  || fail "production release SHA cannot be resolved from Git history"
[[ "$PRODUCTION_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid production SHA"
if [[ "$PRODUCTION_PROVENANCE" == "oci-revision" && "$PRODUCTION_SHA" != "$CURRENT_REVISION" ]]; then
  fail "production OCI revision contradicts resolved Git commit"
fi
git merge-base --is-ancestor "$PRODUCTION_SHA" "$REMOTE_SHA" \
  || fail "running production SHA is not an ancestor of current main"

COMMIT_COUNT="$(git rev-list --count "${PRODUCTION_SHA}..${REMOTE_SHA}")"
[[ "$COMMIT_COUNT" =~ ^[0-9]+$ ]] || fail "invalid cumulative commit count"
if [[ "$COMMIT_COUNT" == "0" ]]; then
  printf '\nNO DEPLOY NEEDED: production already runs exact current main %s.\n' "$REMOTE_SHA"
  exit 0
fi

mapfile -t CHANGED_FILES < <(git diff --name-only "${PRODUCTION_SHA}..${REMOTE_SHA}")
[[ ${#CHANGED_FILES[@]} -gt 0 ]] || fail "cumulative release range has no changed files"

MIGRATION_FOUND=0
COMPOSE_FOUND=0
for path in "${CHANGED_FILES[@]}"; do
  case "$path" in
    backend/alembic.ini|backend/alembic/*|backend/migrations/*|*alembic/versions/*)
      MIGRATION_FOUND=1
      ;;
    docker-compose.yml|docker-compose.production.yml)
      COMPOSE_FOUND=1
      ;;
  esac
done
(( MIGRATION_FOUND == 0 )) \
  || fail "cumulative database migration change detected; VS Code API/UI deploy is not authorized"
(( COMPOSE_FOUND == 0 )) \
  || fail "cumulative Compose change detected; VS Code API/UI deploy is not authorized"

printf '\nHermes Deals cumulative release candidate\n'
printf '  source PR:       #%s — %s\n' "$PR_NUMBER" "$PR_TITLE"
printf '  source issue:    #%s\n' "$SOURCE_ISSUE"
printf '  production tag:  %s\n' "$CURRENT_TAG"
printf '  provenance:      %s\n' "$PRODUCTION_PROVENANCE"
printf '  production SHA:  %s\n' "$PRODUCTION_SHA"
printf '  target main SHA: %s\n' "$REMOTE_SHA"
printf '  commits:         %s\n' "$COMMIT_COUNT"
printf '  changed files:   %s\n' "${#CHANGED_FILES[@]}"
printf '\nCumulative commits:\n'
git --no-pager log --oneline --no-decorate "${PRODUCTION_SHA}..${REMOTE_SHA}"
printf '\nCumulative changed files:\n'
printf '  %s\n' "${CHANGED_FILES[@]}"

create_bridge_request() {
  local request_mode="$1"
  local request_file issue_url issue_number bridge_rc bridge_output status_label state

  request_file="$(mktemp)"
  trap 'rm -f "${request_file:-}"' RETURN
  python3 - "$request_file" "$BRIDGE_MARKER" "$REPO" "$SOURCE_ISSUE" "$PR_NUMBER" "$REMOTE_SHA" "$request_mode" <<'PY'
import json
import pathlib
import sys

path, marker, repository, source_issue, source_pr, release_sha, mode = sys.argv[1:]
payload = {
    "schema_version": 1,
    "repository": repository,
    "release_class": "api-ui",
    "source_issue": int(source_issue),
    "source_pr": int(source_pr),
    "release_sha": release_sha,
    "mode": mode,
    "audit_run_id": None,
    "owner_authorized": True,
    "database_writes_authorized": False,
}
pathlib.Path(path).write_text(
    marker + "\n\n```json\n" + json.dumps(payload, indent=2) + "\n```\n",
    encoding="utf-8",
)
PY

  issue_url="$(gh issue create \
    --repo "$REPO" \
    --title "[Hermes deploy] api-ui ${request_mode} ${REMOTE_SHA:0:7}" \
    --body-file "$request_file" \
    --label "$DEPLOY_LABEL")"
  issue_number="${issue_url##*/}"
  [[ "$issue_number" =~ ^[1-9][0-9]*$ ]] || fail "deploy request issue number could not be resolved"
  printf '\nDeploy request created: %s\n' "$issue_url"

  set +e
  bridge_output="$(sudo --non-interactive /usr/local/sbin/hermes-deals-release-bridge poll 2>&1)"
  bridge_rc=$?
  set -e
  if [[ -n "$bridge_output" ]]; then
    printf '%s\n' "$bridge_output"
  fi
  if (( bridge_rc != 0 )); then
    printf 'Immediate bridge poll returned %s; the five-minute no-agent poll may continue the request.\n' "$bridge_rc"
  fi

  printf 'Waiting for controlled release result...\n'
  for _ in $(seq 1 360); do
    status_label="$(gh issue view "$issue_number" --repo "$REPO" --json labels --jq '[.labels[].name | select(startswith("hermes:deploy-"))][0] // ""')"
    state="$(gh issue view "$issue_number" --repo "$REPO" --json state --jq '.state')"
    case "$status_label" in
      hermes:deploy-pass)
        printf '\n%s PASS: controlled release bridge completed successfully.\n' "${request_mode^^}"
        printf 'Evidence and result: %s\n' "$issue_url"
        return 0
        ;;
      hermes:deploy-fail|hermes:deploy-blocked)
        fail "controlled release bridge ended with ${status_label}; review ${issue_url}"
        ;;
    esac
    [[ "$state" != "CLOSED" ]] || fail "deploy request closed without a PASS label; review ${issue_url}"
    sleep 10
  done
  fail "timed out waiting for deploy request; review ${issue_url}"
}

case "$MODE" in
  check)
    printf '\nCHECK PASS: exact current main is eligible for a controlled bridge request.\n'
    printf 'No production change was made.\n'
    ;;

  plan)
    printf '\nCreating a controlled PLAN request through the root auto-registration bridge...\n'
    create_bridge_request plan
    ;;

  apply)
    printf '\nThis will request deployment of exact current main to production.\n'
    printf 'Required confirmation:\n  APPLY api-ui %s\n' "$REMOTE_SHA"
    read -r -p '> ' CONFIRMATION
    [[ "$CONFIRMATION" == "APPLY api-ui ${REMOTE_SHA}" ]] \
      || fail "confirmation did not match; deployment cancelled"
    create_bridge_request apply
    ;;

  *)
    fail "usage: $0 {check|plan|apply}"
    ;;
esac