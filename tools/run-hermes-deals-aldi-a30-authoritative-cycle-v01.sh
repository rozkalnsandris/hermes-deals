#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
[[ $# -eq 1 ]] || { echo "usage: $0 <registered-sha>" >&2; exit 2; }
EXPECTED_SHA="$1"
AUDIT_REPO="/home/andris/hermes-deals-audit-source"
PRIMARY_REPO="/home/andris/hermes-deals"
PLAN="$AUDIT_REPO/config/aldi-a30-authoritative-cycle-2026cw32-cw33.json"
ENV_FILE="/home/andris/.local/share/hermes-deals/aldi-a30-playwright/playwright-1.61.0/a30-v03.env"
OUT_ROOT="/home/andris/.local/state/hermes-deals/aldi-perfect-shadow/a30-authoritative-cycle-github"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$OUT_ROOT/$STAMP"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "invalid SHA" >&2; exit 2; }
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" ]] || { echo "audit repo missing" >&2; exit 1; }
[[ "$(GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" branch --show-current)" == main ]] || { echo "audit repo branch mismatch" >&2; exit 1; }
[[ "$(GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || { echo "audit repo HEAD mismatch" >&2; exit 1; }
[[ -z "$(GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all)" ]] || { echo "audit repo dirty" >&2; exit 1; }
primary_branch="$(GIT_OPTIONAL_LOCKS=0 git -C "$PRIMARY_REPO" branch --show-current || true)"
primary_head="$(GIT_OPTIONAL_LOCKS=0 git -C "$PRIMARY_REPO" rev-parse HEAD)"
primary_status="$(GIT_OPTIONAL_LOCKS=0 git -C "$PRIMARY_REPO" status --porcelain=v1 -z --untracked-files=all | sha256sum | awk '{print $1}')"
source "$ENV_FILE"
mkdir -p "$OUT"
set +e
PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" "$ALDI_A30_BROWSER_PYTHON" "$AUDIT_REPO/tools/aldi_a30_authoritative_cycle.py" \
  --plan "$PLAN" --output "$OUT/evidence" --browser-executable "$ALDI_A30_BROWSER_EXECUTABLE" --commit-sha "$EXPECTED_SHA"
rc=$?
set -e
[[ "$(GIT_OPTIONAL_LOCKS=0 git -C "$PRIMARY_REPO" branch --show-current || true)" == "$primary_branch" ]]
[[ "$(GIT_OPTIONAL_LOCKS=0 git -C "$PRIMARY_REPO" rev-parse HEAD)" == "$primary_head" ]]
[[ "$(GIT_OPTIONAL_LOCKS=0 git -C "$PRIMARY_REPO" status --porcelain=v1 -z --untracked-files=all | sha256sum | awk '{print $1}')" == "$primary_status" ]]
printf 'REGISTERED_COMMIT=%s\nPRIMARY_WORKTREE_MODIFIED=false\nPRODUCTION_DATABASE_WRITE=false\nPRODUCTION_DEPLOYMENT=false\nB15M2_V08_ACTION=false\nEVIDENCE_DIR=%s\nAUDIT_EXIT_CODE=%s\n' "$EXPECTED_SHA" "$OUT/evidence" "$rc"
exit "$rc"
