#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'run installer with sudo'
[[ $# -eq 1 ]] || fail 'usage: installer <exact-merged-main-sha>'
EXPECTED_SHA="$1"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid merged commit SHA'

AUDIT_REPO='/home/andris/hermes-deals-audit-source'
C3_REL='tools/lidl_v631_c3_readonly_preflight.py'
CORE_REL='backend/app/lidl_v631_c3_readonly_preflight.py'
PLANNER_REL='backend/app/lidl_v631_semantic_persistence.py'
DISPATCHER_REL='tools/runner/lidl-v631-c3-readonly-dispatcher.sh'
DISPATCHER='/usr/local/sbin/hermes-deals-lidl-v631-c3-readonly'
CONF='/etc/hermes-deals-audits.d/lidl-v631-c3-readonly.conf'
SUDOERS='/etc/sudoers.d/hermes-deals-lidl-v631-c3-readonly'
PRIVATE_ROOT='/var/lib/hermes-deals/lidl-v631-c3-readonly-private'
EVIDENCE_ROOT='/var/lib/hermes-deals/lidl-v631-c3-readonly'
RUNNER_SERVICE='actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service'
EXPECTED_C3_BLOB='c31df993e94707ffa35b82c4976f4b79e1154add'
EXPECTED_CORE_BLOB='65273e99a855e3ea26c65329745c5101d4d2d742'
EXPECTED_PLANNER_BLOB='5c183c4459275c99c7d0f9d66a7a5c425384a5be'
EXPECTED_DISPATCHER_BLOB='de26a292d727a89f9ad2b701a543897b6f87224b'

for user in andris github-runner; do id "$user" >/dev/null 2>&1 || fail "required user missing: $user"; done
for command in bash docker git grep head id install mktemp readlink rm runuser sha256sum stat sudo systemctl visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command missing: $command"
done
AUDIT_REPO="$(readlink -f -- "$AUDIT_REPO")"
[[ "$AUDIT_REPO" == /home/andris/hermes-deals-audit-source ]] || fail 'audit repository path drift'
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" ]] || fail 'audit repository missing or unsafe'
[[ "$(stat -c '%U:%G' "$AUDIT_REPO")" == andris:andris ]] || fail 'audit repository ownership mismatch'
INDEX="$AUDIT_REPO/.git/index"
[[ -f "$INDEX" && ! -L "$INDEX" ]] || fail 'audit Git index missing or unsafe'
[[ "$(stat -c '%U:%G' "$INDEX")" == andris:andris ]] || fail 'audit Git index ownership mismatch'
[[ ! -e "$INDEX.lock" ]] || fail 'audit Git index lock exists'
INDEX_SHA_BEFORE="$(sha256sum "$INDEX" | awk '{print $1}')"
INDEX_STAT_BEFORE="$(stat -c '%U:%G:%a:%s:%Y' "$INDEX")"

git_read() { runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" "$@"; }
BRANCH="$(git_read branch --show-current)"
HEAD_SHA="$(git_read rev-parse HEAD)"
STATUS="$(git_read status --porcelain=v1 --untracked-files=all)"
[[ "$BRANCH" == main && "$HEAD_SHA" == "$EXPECTED_SHA" && -z "$STATUS" ]] || fail 'audit clone is not exact clean main at installer SHA'
ORIGIN="$(git_read remote get-url origin)"
case "$ORIGIN" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail 'audit origin is not allowlisted' ;;
esac

for spec in "$C3_REL:$EXPECTED_C3_BLOB" "$CORE_REL:$EXPECTED_CORE_BLOB" "$PLANNER_REL:$EXPECTED_PLANNER_BLOB" "$DISPATCHER_REL:$EXPECTED_DISPATCHER_BLOB"; do
  path="${spec%%:*}"; expected="${spec##*:}"
  git_read cat-file -e "$EXPECTED_SHA:$path" || fail "registered file missing: $path"
  [[ "$(git_read rev-parse "$EXPECTED_SHA:$path")" == "$expected" ]] || fail "registered blob identity drift: $path"
done

TMP="$(mktemp -d /tmp/hermes-deals-lidl-v631-c3-install.XXXXXX)"
cleanup() { rm -rf -- "$TMP"; }
trap cleanup EXIT
git_read show "$EXPECTED_SHA:$DISPATCHER_REL" > "$TMP/dispatcher.sh"
[[ -s "$TMP/dispatcher.sh" ]] || fail 'dispatcher source empty'
head -n 1 "$TMP/dispatcher.sh" | grep -Fxq '#!/usr/bin/env bash' || fail 'dispatcher header invalid'
bash -n "$TMP/dispatcher.sh"

cat > "$TMP/sudoers" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-lidl-v631-c3-readonly env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-lidl-v631-c3-readonly *
SUDOERS
chmod 0440 "$TMP/sudoers"
visudo -cf "$TMP/sudoers" >/dev/null

install -d -o root -g root -m 0755 /etc/hermes-deals-audits.d /var/lib/hermes-deals
install -d -o root -g root -m 0700 "$PRIVATE_ROOT"
install -d -o root -g root -m 0755 "$EVIDENCE_ROOT"
install -o root -g root -m 0755 "$TMP/dispatcher.sh" "$DISPATCHER"
install -o root -g root -m 0440 "$TMP/sudoers" "$SUDOERS"
DISPATCHER_SHA="$(sha256sum "$DISPATCHER" | awk '{print $1}')"
CONF_TMP="$(mktemp /etc/hermes-deals-audits.d/.lidl-v631-c3-readonly.conf.XXXXXX)"
cat > "$CONF_TMP" <<CONF
audit_name='lidl-v631-c3-readonly'
registered_merge_sha='$EXPECTED_SHA'
c3_blob='$EXPECTED_C3_BLOB'
core_blob='$EXPECTED_CORE_BLOB'
planner_blob='$EXPECTED_PLANNER_BLOB'
dispatcher_blob='$EXPECTED_DISPATCHER_BLOB'
dispatcher_sha256='$DISPATCHER_SHA'
CONF
chown root:root "$CONF_TMP"
chmod 0644 "$CONF_TMP"
mv -f -- "$CONF_TMP" "$CONF"

[[ "$(sha256sum "$INDEX" | awk '{print $1}')" == "$INDEX_SHA_BEFORE" ]] || fail 'audit Git index content changed during installation'
[[ "$(stat -c '%U:%G:%a:%s:%Y' "$INDEX")" == "$INDEX_STAT_BEFORE" ]] || fail 'audit Git index metadata changed during installation'
[[ ! -e "$INDEX.lock" ]] || fail 'installer left audit Git index lock'
[[ "$(stat -c '%U:%G:%a' "$PRIVATE_ROOT")" == root:root:700 ]] || fail 'private C3 root metadata mismatch'
[[ "$(stat -c '%U:%G:%a' "$EVIDENCE_ROOT")" == root:root:755 ]] || fail 'sanitized C3 evidence root metadata mismatch'
visudo -cf "$SUDOERS" >/dev/null
systemctl is-active --quiet "$RUNNER_SERVICE" || fail 'GitHub Actions audit runner service is not active'
sudo -l -U github-runner | grep -Fq "$DISPATCHER" || fail 'github-runner dispatcher sudo rule missing'
RUNNER_HAS_DOCKER="$(id -nG github-runner | tr ' ' '\n' | grep -Fxq docker && echo true || echo false)"
[[ "$RUNNER_HAS_DOCKER" == false ]] || fail 'github-runner must not belong to docker group'

printf 'INSTALL_RESULT=PASS\n'
printf 'AUDIT=lidl-v631-c3-readonly\nREGISTERED_COMMIT=%s\n' "$EXPECTED_SHA"
printf 'C3_BLOB_SHA=%s\nCORE_BLOB_SHA=%s\nPLANNER_BLOB_SHA=%s\nDISPATCHER_BLOB_SHA=%s\n' "$EXPECTED_C3_BLOB" "$EXPECTED_CORE_BLOB" "$EXPECTED_PLANNER_BLOB" "$EXPECTED_DISPATCHER_BLOB"
printf 'DISPATCHER_SHA256=%s\n' "$DISPATCHER_SHA"
printf 'AUDIT_GIT_INDEX_UNCHANGED=true\nSUDOERS_VALID=true\nRUNNER_HAS_DOCKER_GROUP=false\n'
printf 'PRIVATE_STAGING_ROOT=%s\nSANITIZED_EVIDENCE_ROOT=%s\n' "$PRIVATE_ROOT" "$EVIDENCE_ROOT"
printf 'PRODUCTION_DATABASE_WRITE=false\nCORPUS_WRITE=false\nREVIEW_WRITE=false\nPRODUCTION_PUBLISH=false\nPRODUCTION_DEPLOY=false\nSYSTEMD_CHANGE=false\nSCHEDULER_CHANGE=false\n'
printf 'NOTE=installer changes root-owned dispatcher registration/evidence roots only; execution requires separate owner authorization\n'
