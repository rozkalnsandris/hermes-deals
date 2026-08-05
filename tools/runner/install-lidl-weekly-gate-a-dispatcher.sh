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
RUNNER_SOURCE='tools/run-hermes-deals-lidl-weekly-gate-a-v01.sh'
DISPATCHER_SOURCE='tools/runner/lidl-weekly-gate-a-dispatcher.sh'
RUNNER_SERVICE='actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service'
INSTALLED_SCRIPT='/usr/local/libexec/hermes-deals-audits/lidl-weekly-gate-a.sh'
DISPATCHER='/usr/local/sbin/hermes-deals-lidl-weekly-gate-a-dispatch'
CONF='/etc/hermes-deals-audits.d/lidl-weekly-gate-a.conf'
SUDOERS='/etc/sudoers.d/hermes-deals-lidl-weekly-gate-a'
IMAGE_TAG="hermes-deals-lidl-gate-a:${EXPECTED_SHA}"

for user in andris github-runner; do id "$user" >/dev/null 2>&1 || fail "required user is missing: $user"; done
for command in bash docker git grep head id install mktemp readlink rm runuser sha256sum stat sudo systemctl visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
AUDIT_REPO="$(readlink -f -- "$AUDIT_REPO")"
[[ "$AUDIT_REPO" == /home/andris/hermes-deals-audit-source ]] || fail 'audit repository path drift'
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" ]] || fail 'audit repository is missing or unsafe'
[[ "$(stat -c '%U:%G' "$AUDIT_REPO")" == andris:andris ]] || fail 'audit repository ownership mismatch'
INDEX="$AUDIT_REPO/.git/index"
[[ -f "$INDEX" && ! -L "$INDEX" ]] || fail 'audit Git index is missing or unsafe'
[[ "$(stat -c '%U:%G' "$INDEX")" == andris:andris ]] || fail 'audit Git index ownership mismatch'
[[ ! -e "$INDEX.lock" ]] || fail 'audit Git index lock exists'
INDEX_SHA_BEFORE="$(sha256sum "$INDEX" | awk '{print $1}')"
INDEX_STAT_BEFORE="$(stat -c '%U:%G:%a:%s:%Y' "$INDEX")"

git_read() { runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" "$@"; }
BRANCH="$(git_read branch --show-current)" || fail 'cannot read audit branch'
HEAD_SHA="$(git_read rev-parse HEAD)" || fail 'cannot read audit HEAD'
STATUS="$(git_read status --porcelain=v1 --untracked-files=all)" || fail 'cannot read audit status'
[[ "$BRANCH" == main && "$HEAD_SHA" == "$EXPECTED_SHA" && -z "$STATUS" ]] || fail 'audit clone is not exact clean main at registered SHA'
git_read merge-base --is-ancestor "$EXPECTED_SHA" main || fail 'registered SHA is not reachable from audit main'
ORIGIN="$(git_read remote get-url origin)" || fail 'cannot read audit origin'
case "$ORIGIN" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail 'audit origin is not allowlisted' ;;
esac
for path in "$RUNNER_SOURCE" "$DISPATCHER_SOURCE" backend/Dockerfile backend/requirements.txt; do
  git_read cat-file -e "$EXPECTED_SHA:$path" || fail "registered file is missing: $path"
done

TMP="$(mktemp -d /tmp/hermes-deals-lidl-gate-a-install.XXXXXX)"
cleanup() { rm -rf -- "$TMP"; }
trap cleanup EXIT
git_read show "$EXPECTED_SHA:$RUNNER_SOURCE" > "$TMP/runner.sh"
git_read show "$EXPECTED_SHA:$DISPATCHER_SOURCE" > "$TMP/dispatcher.sh"
for file in runner.sh dispatcher.sh; do
  [[ -s "$TMP/$file" ]] || fail "$file is empty"
  head -n 1 "$TMP/$file" | grep -Fxq '#!/usr/bin/env bash' || fail "$file header is invalid"
  bash -n "$TMP/$file"
done

cat > "$TMP/sudoers" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-lidl-weekly-gate-a-dispatch env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-lidl-weekly-gate-a-dispatch *
SUDOERS
chmod 0440 "$TMP/sudoers"
visudo -cf "$TMP/sudoers" >/dev/null

DOCKERFILE_SHA="$(sha256sum "$AUDIT_REPO/backend/Dockerfile" | awk '{print $1}')"
REQUIREMENTS_SHA="$(sha256sum "$AUDIT_REPO/backend/requirements.txt" | awk '{print $1}')"
docker build --pull=false \
  --label "net.rozkalns.hermes-deals.audit=lidl-weekly-gate-a" \
  --label "net.rozkalns.hermes-deals.commit=$EXPECTED_SHA" \
  --label "net.rozkalns.hermes-deals.dockerfile-sha256=$DOCKERFILE_SHA" \
  --label "net.rozkalns.hermes-deals.requirements-sha256=$REQUIREMENTS_SHA" \
  --tag "$IMAGE_TAG" \
  "$AUDIT_REPO/backend"
IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE_TAG")"
[[ "$IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || fail 'built image ID is invalid'
[[ "$(docker image inspect --format '{{index .Config.Labels "net.rozkalns.hermes-deals.commit"}}' "$IMAGE_ID")" == "$EXPECTED_SHA" ]] || fail 'built image commit label mismatch'
[[ "$(docker image inspect --format '{{index .Config.Labels "net.rozkalns.hermes-deals.dockerfile-sha256"}}' "$IMAGE_ID")" == "$DOCKERFILE_SHA" ]] || fail 'built image Dockerfile label mismatch'
[[ "$(docker image inspect --format '{{index .Config.Labels "net.rozkalns.hermes-deals.requirements-sha256"}}' "$IMAGE_ID")" == "$REQUIREMENTS_SHA" ]] || fail 'built image requirements label mismatch'

install -d -o root -g root -m 0755 /usr/local/libexec/hermes-deals-audits /etc/hermes-deals-audits.d
install -d -o andris -g andris -m 0700 /home/andris/hermes-deals-runner-evidence /home/andris/hermes-deals-lidl-gate-a-evidence
install -o root -g root -m 0755 "$TMP/runner.sh" "$INSTALLED_SCRIPT"
install -o root -g root -m 0755 "$TMP/dispatcher.sh" "$DISPATCHER"
install -o root -g root -m 0440 "$TMP/sudoers" "$SUDOERS"
SCRIPT_SHA="$(sha256sum "$INSTALLED_SCRIPT" | awk '{print $1}')"
DISPATCHER_SHA="$(sha256sum "$DISPATCHER" | awk '{print $1}')"
CONF_TMP="$(mktemp /etc/hermes-deals-audits.d/.lidl-weekly-gate-a.conf.XXXXXX)"
cat > "$CONF_TMP" <<CONF
audit_name='lidl-weekly-gate-a'
commit_sha='$EXPECTED_SHA'
script_path='$INSTALLED_SCRIPT'
script_sha256='$SCRIPT_SHA'
image_id='$IMAGE_ID'
image_tag='$IMAGE_TAG'
dockerfile_sha256='$DOCKERFILE_SHA'
requirements_sha256='$REQUIREMENTS_SHA'
CONF
chown root:root "$CONF_TMP"
chmod 0644 "$CONF_TMP"
mv -f -- "$CONF_TMP" "$CONF"

[[ "$(sha256sum "$INDEX" | awk '{print $1}')" == "$INDEX_SHA_BEFORE" ]] || fail 'audit Git index content changed during installation'
[[ "$(stat -c '%U:%G:%a:%s:%Y' "$INDEX")" == "$INDEX_STAT_BEFORE" ]] || fail 'audit Git index metadata changed during installation'
[[ ! -e "$INDEX.lock" ]] || fail 'installer left an audit Git index lock'
visudo -cf "$SUDOERS" >/dev/null
systemctl is-active --quiet "$RUNNER_SERVICE" || fail 'GitHub Actions audit runner service is not active'
sudo -l -U github-runner | grep -Fq "$DISPATCHER" || fail 'github-runner dispatcher sudo rule is missing'
RUNNER_HAS_DOCKER="$(id -nG github-runner | tr ' ' '\n' | grep -Fxq docker && echo true || echo false)"
[[ "$RUNNER_HAS_DOCKER" == false ]] || fail 'github-runner must not belong to docker group'

printf 'INSTALL_RESULT=PASS\n'
printf 'AUDIT=lidl-weekly-gate-a\n'
printf 'REGISTERED_COMMIT=%s\n' "$EXPECTED_SHA"
printf 'REGISTERED_IMAGE_ID=%s\n' "$IMAGE_ID"
printf 'DOCKERFILE_SHA256=%s\n' "$DOCKERFILE_SHA"
printf 'REQUIREMENTS_SHA256=%s\n' "$REQUIREMENTS_SHA"
printf 'SCRIPT_SHA256=%s\n' "$SCRIPT_SHA"
printf 'DISPATCHER_SHA256=%s\n' "$DISPATCHER_SHA"
printf 'AUDIT_GIT_INDEX_UNCHANGED=true\nSUDOERS_VALID=true\nRUNNER_HAS_DOCKER_GROUP=false\n'
printf 'PRODUCTION_DATABASE_WRITE=false\nREVIEW_WRITE=false\nPRODUCTION_PUBLISH=false\nPRODUCTION_DEPLOY=false\nSYSTEMD_CHANGE=false\n'
