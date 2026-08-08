#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

PRIMARY='/home/andris/hermes-deals'
AUDIT_REPO='/home/andris/hermes-deals-audit-source-lidl-refresh'
REPOSITORY='rozkalnsandris/hermes-deals'
V08_SCRIPT="$PRIMARY/tools/run-hermes-deals-b15m2-least-privilege-shadow-migration-api-regression-v08.sh"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ $# -eq 2 ]] || fail 'usage: finalizer <merged-sha> <merged-pr>'
TARGET_SHA="$1"; PR_NUMBER="$2"
[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'merged SHA invalid'
[[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]] || fail 'merged PR invalid'
[[ "$(id -un)" == andris ]] || fail 'owner finalizer must run as andris'
for command in gh git grep readlink sha256sum stat sudo tee visudo; do command -v "$command" >/dev/null 2>&1 || fail "required command missing: $command"; done

file_state() {
  local path="$1"
  if [[ ! -e "$path" ]]; then printf 'missing\n'; return; fi
  [[ -f "$path" && ! -L "$path" ]] || fail "unsafe protected file: $path"
  printf '%s:%s:%s\n' "$(stat -c '%U:%G:%a:%s' "$path")" "$(sha256sum "$path" | awk '{print $1}')" "$(readlink -f -- "$path")"
}
git_read() { local repo="$1"; shift; GIT_OPTIONAL_LOCKS=0 git -C "$repo" "$@"; }

[[ "$(readlink -f -- "$PRIMARY")" == "$PRIMARY" && -e "$PRIMARY/.git" ]] || fail 'primary repository path unsafe'
PRIMARY_BRANCH_BEFORE="$(git_read "$PRIMARY" branch --show-current)"
PRIMARY_HEAD_BEFORE="$(git_read "$PRIMARY" rev-parse HEAD)"
PRIMARY_STATUS_BEFORE="$(git_read "$PRIMARY" status --porcelain=v1 --untracked-files=all)"
PRIMARY_INDEX_PATH="$(git_read "$PRIMARY" rev-parse --path-format=absolute --git-path index)"
[[ -f "$PRIMARY_INDEX_PATH" && ! -L "$PRIMARY_INDEX_PATH" && ! -e "${PRIMARY_INDEX_PATH}.lock" ]] || fail 'primary Git index unsafe'
PRIMARY_INDEX_BEFORE="$(file_state "$PRIMARY_INDEX_PATH")"
PRIMARY_V08_BEFORE="$(file_state "$V08_SCRIPT")"
FAMILY='/home/andris/hermes-deals-lidl-corpus/flyers/aktionsprospekt-03-08-2026-08-08-2026-b1cf3b--src-6da2135ea984'
[[ -d "$FAMILY" && ! -L "$FAMILY" ]] || fail 'rev05 family missing'
SOURCE_PDF_BEFORE="$(file_state "$FAMILY/source.pdf")"
SOURCE_JSON_BEFORE="$(file_state "$FAMILY/source.json")"
[[ ! -e "$FAMILY/review-profile.json" && ! -L "$FAMILY/review-profile.json" ]] || fail 'rev05 review-profile must be absent'
[[ ! -e "$FAMILY/scans/scan-v631-7191e910f07b" && ! -L "$FAMILY/scans/scan-v631-7191e910f07b" ]] || fail 'R3 scan target already occupied'
[[ ! -e "$FAMILY/source-refresh/e6ebe5669551a2d455e7b2c036746e08e3bdd20e8e0562fab6972ab97e2a88e8" && ! -L "$FAMILY/source-refresh/e6ebe5669551a2d455e7b2c036746e08e3bdd20e8e0562fab6972ab97e2a88e8" ]] || fail 'R3 refresh target already occupied'

verify_primary() {
  [[ "$(git_read "$PRIMARY" branch --show-current)" == "$PRIMARY_BRANCH_BEFORE" ]] || fail 'primary branch changed'
  [[ "$(git_read "$PRIMARY" rev-parse HEAD)" == "$PRIMARY_HEAD_BEFORE" ]] || fail 'primary HEAD changed'
  [[ "$(git_read "$PRIMARY" status --porcelain=v1 --untracked-files=all)" == "$PRIMARY_STATUS_BEFORE" ]] || fail 'primary status changed'
  [[ "$(file_state "$PRIMARY_INDEX_PATH")" == "$PRIMARY_INDEX_BEFORE" ]] || fail 'primary Git index changed'
  [[ ! -e "${PRIMARY_INDEX_PATH}.lock" ]] || fail 'primary Git index lock appeared'
  [[ "$(file_state "$V08_SCRIPT")" == "$PRIMARY_V08_BEFORE" ]] || fail 'protected V08 state changed'
  [[ "$(file_state "$FAMILY/source.pdf")" == "$SOURCE_PDF_BEFORE" ]] || fail 'immutable PDF changed'
  [[ "$(file_state "$FAMILY/source.json")" == "$SOURCE_JSON_BEFORE" ]] || fail 'immutable source JSON changed'
  [[ ! -e "$FAMILY/review-profile.json" && ! -L "$FAMILY/review-profile.json" ]] || fail 'rev05 profile appeared'
  [[ ! -e "$FAMILY/scans/scan-v631-7191e910f07b" && ! -L "$FAMILY/scans/scan-v631-7191e910f07b" ]] || fail 'bootstrap executed R3 scan promotion'
  [[ ! -e "$FAMILY/source-refresh/e6ebe5669551a2d455e7b2c036746e08e3bdd20e8e0562fab6972ab97e2a88e8" && ! -L "$FAMILY/source-refresh/e6ebe5669551a2d455e7b2c036746e08e3bdd20e8e0562fab6972ab97e2a88e8" ]] || fail 'bootstrap executed R3 authority promotion'
}

printf '=== Lidl R3 promotion owner bootstrap ===\nUTC=%s\nTARGET_SHA=%s\nPR_NUMBER=%s\nPRIMARY_HEAD_BEFORE=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TARGET_SHA" "$PR_NUMBER" "$PRIMARY_HEAD_BEFORE"
gh auth status >/dev/null
MERGED="$(gh api "repos/$REPOSITORY/pulls/$PR_NUMBER" --jq '.merged')"
MERGED_AT="$(gh api "repos/$REPOSITORY/pulls/$PR_NUMBER" --jq '.merged_at // ""')"
MERGE_SHA="$(gh api "repos/$REPOSITORY/pulls/$PR_NUMBER" --jq '.merge_commit_sha // ""')"
BASE_REF="$(gh api "repos/$REPOSITORY/pulls/$PR_NUMBER" --jq '.base.ref // ""')"
BASE_REPO="$(gh api "repos/$REPOSITORY/pulls/$PR_NUMBER" --jq '.base.repo.full_name // ""')"
[[ "$MERGED" == true && -n "$MERGED_AT" && "$MERGE_SHA" == "$TARGET_SHA" ]] || fail 'PR merge identity mismatch'
[[ "$BASE_REF" == main && "$BASE_REPO" == "$REPOSITORY" ]] || fail 'PR was not merged into repository main'

if [[ ! -e "$AUDIT_REPO" ]]; then git clone --no-tags "https://github.com/$REPOSITORY.git" "$AUDIT_REPO"; fi
[[ "$(readlink -f -- "$AUDIT_REPO")" == "$AUDIT_REPO" ]] || fail 'audit repository path drift'
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" && "$(stat -c '%U:%G' "$AUDIT_REPO")" == andris:andris ]] || fail 'audit repository unsafe'
[[ -z "$(git_read "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail 'audit repository dirty'
ORIGIN="$(git_read "$AUDIT_REPO" remote get-url origin)"
case "$ORIGIN" in https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git) ;; *) fail 'audit origin not allowlisted' ;; esac

git -C "$AUDIT_REPO" fetch --prune origin main
git_read "$AUDIT_REPO" cat-file -e "$TARGET_SHA^{commit}"
git_read "$AUDIT_REPO" merge-base --is-ancestor "$TARGET_SHA" origin/main
git -C "$AUDIT_REPO" switch -C main "$TARGET_SHA"
[[ "$(git_read "$AUDIT_REPO" branch --show-current)" == main && "$(git_read "$AUDIT_REPO" rev-parse HEAD)" == "$TARGET_SHA" ]] || fail 'audit exact SHA switch failed'
[[ -z "$(git_read "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail 'audit repository became dirty'
verify_primary

INSTALL_LOG="$(mktemp /tmp/hermes-lidl-r3-install.XXXXXX)"
trap 'rm -f -- "$INSTALL_LOG"' EXIT
INSTALLER="$AUDIT_REPO/tools/runner/install-lidl-r3-promotion-dispatcher.sh"
[[ -f "$INSTALLER" && ! -L "$INSTALLER" ]] || fail 'R3 installer missing or unsafe'
set +e
sudo bash "$INSTALLER" "$TARGET_SHA" 2>&1 | tee "$INSTALL_LOG"
INSTALL_RC=${PIPESTATUS[0]}
set -e
[[ "$INSTALL_RC" -eq 0 ]] || fail 'R3 installer failed'
for marker in \
 'INSTALL_RESULT=PASS' 'AUDIT=lidl-r3-promotion' "REGISTERED_COMMIT=$TARGET_SHA" \
 'SUDOERS_VALID=true' 'RUNNER_HAS_DOCKER_GROUP=false' 'PROMOTION_EXECUTED=false' \
 'CORPUS_WRITE=false' 'PARSER_SCAN=false' 'PRODUCTION_DATABASE_WRITE=false' 'REVIEW_WRITE=false' \
 'PRODUCTION_PUBLISH=false' 'PRODUCTION_DEPLOY=false' 'SYSTEMD_CHANGE=false' 'AUTOMATIC_RETRY=false' \
 'GATE_C_D_AUTHORIZED=false' 'B15M2_V08_AUTHORIZED=false'; do
  grep -Fxq "$marker" "$INSTALL_LOG" || fail "installer marker missing: $marker"
done
sudo visudo -cf /etc/sudoers.d/hermes-deals-lidl-r3-promotion >/dev/null
sudo -l -U github-runner | grep -Fq '/usr/local/sbin/hermes-deals-lidl-r3-promotion-dispatch' || fail 'runner R3 dispatcher authorization missing'
[[ -z "$(git_read "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail 'audit repository changed during install'
[[ "$(git_read "$AUDIT_REPO" rev-parse HEAD)" == "$TARGET_SHA" ]] || fail 'audit HEAD changed during install'
verify_primary

printf 'OWNER_BOOTSTRAP_RESULT=PASS\nAUDIT_CLONE_HEAD=%s\n' "$TARGET_SHA"
printf 'PROMOTION_EXECUTED=false\nCORPUS_WRITE=false\nPARSER_SCAN=false\nPRODUCTION_DATABASE_WRITE=false\nREVIEW_WRITE=false\nPRODUCTION_PUBLISH=false\nPRODUCTION_DEPLOY=false\nSYSTEMD_CHANGE=false\nAUTOMATIC_RETRY=false\nGATE_C_D_AUTHORIZED=false\nB15M2_V08_AUTHORIZED=false\nPRIMARY_INVARIANCE=true\nIMMUTABLE_SOURCE_INVARIANCE=true\n'
printf 'NEXT_GITHUB_COMMAND=/hermes-lidl-source-refresh-r3-promote pr=%s fingerprint=8aaf1f96a119e51c980a45da80031d5abd2db65d4cdc3516bd5368fd0537c7f9 auth=5227260615\n' "$PR_NUMBER"
