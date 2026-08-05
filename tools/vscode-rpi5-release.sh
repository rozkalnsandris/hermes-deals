#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

MODE="${1:-check}"
REPO="rozkalnsandris/hermes-deals"
WORKFLOW="rpi5-release-command.yml"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

command -v git >/dev/null 2>&1 || fail "git is not installed"
command -v gh >/dev/null 2>&1 || fail "GitHub CLI (gh) is not installed on RPi5"
gh auth status >/dev/null 2>&1 || fail "GitHub CLI is not authenticated; run: gh auth login"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "open the Hermes Deals repository in VS Code"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

BRANCH="$(git branch --show-current)"
[[ "$BRANCH" == "main" ]] || fail "deploy tasks may run only from the main branch (current: ${BRANCH:-detached})"

if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  fail "the RPi5 primary worktree is not clean; commit, move, or remove local changes first"
fi

printf 'Fetching origin/main...\n'
git fetch --quiet origin main
LOCAL_SHA="$(git rev-parse HEAD)"
REMOTE_SHA="$(git rev-parse origin/main)"
[[ "$LOCAL_SHA" == "$REMOTE_SHA" ]] || fail "local main is not synchronized with origin/main; use fast-forward pull before release"
[[ "$REMOTE_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid main SHA"

PR_JSON="$(gh api \
  -H 'Accept: application/vnd.github+json' \
  "/repos/${REPO}/commits/${REMOTE_SHA}/pulls")"
PR_NUMBER="$(python3 -c '
import json, sys
items = json.load(sys.stdin)
valid = [p for p in items if p.get("merged_at") and p.get("base", {}).get("ref") == "main"]
if len(valid) != 1:
    raise SystemExit(2)
print(valid[0]["number"])
' <<<"$PR_JSON")" || fail "current main SHA is not bound to exactly one merged PR"

PR_TITLE="$(gh api "/repos/${REPO}/pulls/${PR_NUMBER}" --jq '.title')"
mapfile -t CHANGED_FILES < <(gh api --paginate "/repos/${REPO}/pulls/${PR_NUMBER}/files?per_page=100" --jq '.[].filename')

printf '\nHermes Deals release candidate\n'
printf '  PR:        #%s — %s\n' "$PR_NUMBER" "$PR_TITLE"
printf '  main SHA:  %s\n' "$REMOTE_SHA"
printf '  files:     %s\n' "${#CHANGED_FILES[@]}"
printf '\nChanged files:\n'
printf '  %s\n' "${CHANGED_FILES[@]}"

MIGRATION_FOUND=0
for path in "${CHANGED_FILES[@]}"; do
  case "$path" in
    backend/alembic/*|backend/migrations/*|*alembic/versions/*)
      MIGRATION_FOUND=1
      ;;
  esac
done

if (( MIGRATION_FOUND )); then
  fail "database migration detected; the VS Code API/UI release path must not deploy migrations"
fi

case "$MODE" in
  check)
    printf '\nCHECK PASS: repository is synchronized and eligible for controlled planning.\n'
    printf 'No production change was made.\n'
    ;;

  plan)
    printf '\nStarting controlled PLAN workflow...\n'
    gh workflow run "$WORKFLOW" \
      --repo "$REPO" \
      --ref main \
      -f release_class=api-ui \
      -f pr_number="$PR_NUMBER" \
      -f release_sha="$REMOTE_SHA" \
      -f mode=plan \
      -f audit_run_id='' \
      -f authorization=''
    sleep 3
    RUN_ID="$(gh run list --repo "$REPO" --workflow "$WORKFLOW" --branch main --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId')"
    [[ "$RUN_ID" =~ ^[0-9]+$ ]] || fail "workflow was dispatched but its run ID could not be resolved"
    printf 'PLAN run: %s\n' "$RUN_ID"
    gh run watch "$RUN_ID" --repo "$REPO" --exit-status
    printf '\nPLAN PASS. Review the workflow evidence before choosing Apply.\n'
    ;;

  apply)
    printf '\nThis will deploy exact current main to production.\n'
    printf 'Required confirmation:\n  APPLY api-ui %s\n' "$REMOTE_SHA"
    read -r -p '> ' CONFIRMATION
    [[ "$CONFIRMATION" == "APPLY api-ui ${REMOTE_SHA}" ]] || fail "confirmation did not match; deployment cancelled"

    printf '\nStarting controlled APPLY workflow...\n'
    gh workflow run "$WORKFLOW" \
      --repo "$REPO" \
      --ref main \
      -f release_class=api-ui \
      -f pr_number="$PR_NUMBER" \
      -f release_sha="$REMOTE_SHA" \
      -f mode=apply \
      -f audit_run_id='' \
      -f authorization="$CONFIRMATION"
    sleep 3
    RUN_ID="$(gh run list --repo "$REPO" --workflow "$WORKFLOW" --branch main --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId')"
    [[ "$RUN_ID" =~ ^[0-9]+$ ]] || fail "workflow was dispatched but its run ID could not be resolved"
    printf 'APPLY run: %s\n' "$RUN_ID"
    gh run watch "$RUN_ID" --repo "$REPO" --exit-status
    printf '\nDEPLOY PASS: controlled production workflow completed successfully.\n'
    ;;

  *)
    fail "usage: $0 {check|plan|apply}"
    ;;
esac
