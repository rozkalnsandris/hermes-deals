#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'run installer with sudo'
[[ $# -eq 1 ]] || fail 'usage: installer <exact-merged-main-sha>'
EXPECTED_SHA="$1"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid merged commit SHA'

SOURCE_ROOT="$(readlink -f -- "$(dirname -- "${BASH_SOURCE[0]}")/../..")"
[[ -d "$SOURCE_ROOT/.git" && ! -L "$SOURCE_ROOT/.git" ]] || fail 'source checkout is missing or unsafe'
[[ "$(stat -c '%U:%G' "$SOURCE_ROOT")" == 'andris:andris' ]] || fail 'source checkout ownership mismatch'

OPERATOR_SOURCE='tools/runner/release/hermes-deals-web-dual-bind-cutover'
DISPATCHER_SOURCE='tools/runner/release/hermes-deals-307-phase-c-dispatch'
EXPECTED_OPERATOR_SHA256='083cbd27990ebcff0d4c9cb81443318a9837f1179555d9921086f47be5cd8d4e'
INSTALLED_OPERATOR='/usr/local/libexec/hermes-deals-ops/issue-307/hermes-deals-web-dual-bind-cutover'
INSTALLED_DISPATCHER='/usr/local/sbin/hermes-deals-307-phase-c-dispatch'
SUDOERS='/etc/sudoers.d/hermes-deals-307-phase-c'
CONF='/etc/hermes-deals-audits.d/issue-307-phase-c.conf'

for user in andris github-runner; do
  id "$user" >/dev/null 2>&1 || fail "required user is missing: $user"
done
for command in awk bash cat chmod chown dirname git grep head id install mktemp mv readlink rm runuser sha256sum stat sudo tr visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

git_read() {
  runuser -u andris -- env \
    HOME=/home/andris \
    GIT_OPTIONAL_LOCKS=0 \
    PATH='/home/andris/.local/bin:/usr/local/bin:/usr/bin:/bin' \
    git -C "$SOURCE_ROOT" "$@"
}

HEAD_SHA="$(git_read rev-parse HEAD)" || fail 'cannot read source HEAD'
STATUS="$(git_read status --porcelain=v1 --untracked-files=all)" || fail 'cannot read source status'
[[ "$HEAD_SHA" == "$EXPECTED_SHA" && -z "$STATUS" ]] || fail 'source checkout is not exact clean registered SHA'
ORIGIN="$(git_read remote get-url origin)" || fail 'cannot read source origin'
case "$ORIGIN" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail 'source origin is not allowlisted' ;;
esac

git_read cat-file -e "$EXPECTED_SHA:$OPERATOR_SOURCE" || fail 'registered operator source is missing'
git_read cat-file -e "$EXPECTED_SHA:$DISPATCHER_SOURCE" || fail 'registered dispatcher source is missing'

TMP="$(mktemp -d /tmp/hermes-deals-307-dispatch-install.XXXXXX)"
cleanup() { rm -rf -- "$TMP"; }
trap cleanup EXIT

git_read show "$EXPECTED_SHA:$OPERATOR_SOURCE" > "$TMP/operator"
git_read show "$EXPECTED_SHA:$DISPATCHER_SOURCE" > "$TMP/dispatcher"
[[ -s "$TMP/operator" && -s "$TMP/dispatcher" ]] || fail 'registered runtime files are empty'
head -n 1 "$TMP/operator" | grep -Fxq '#!/usr/bin/env bash' || fail 'operator header is invalid'
head -n 1 "$TMP/dispatcher" | grep -Fxq '#!/usr/bin/env bash' || fail 'dispatcher header is invalid'
bash -n "$TMP/operator"
bash -n "$TMP/dispatcher"
printf '%s  %s\n' "$EXPECTED_OPERATOR_SHA256" "$TMP/operator" | sha256sum -c - >/dev/null \
  || fail 'registered operator SHA256 mismatch'
DISPATCHER_SHA256="$(sha256sum "$TMP/dispatcher" | awk '{print $1}')"
[[ "$DISPATCHER_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail 'dispatcher SHA256 is invalid'

cat > "$TMP/sudoers" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-307-phase-c-dispatch env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-307-phase-c-dispatch check, /usr/local/sbin/hermes-deals-307-phase-c-dispatch apply-dual, /usr/local/sbin/hermes-deals-307-phase-c-dispatch verify-dual
SUDOERS
chmod 0440 "$TMP/sudoers"
visudo -cf "$TMP/sudoers" >/dev/null

install -d -o root -g root -m 0755 /usr/local/libexec/hermes-deals-ops
install -d -o root -g root -m 0755 /usr/local/libexec/hermes-deals-ops/issue-307
install -d -o root -g root -m 0755 /etc/hermes-deals-audits.d
install -o root -g root -m 0755 "$TMP/operator" "$INSTALLED_OPERATOR"
install -o root -g root -m 0755 "$TMP/dispatcher" "$INSTALLED_DISPATCHER"
install -o root -g root -m 0440 "$TMP/sudoers" "$SUDOERS"

INSTALLED_OPERATOR_SHA256="$(sha256sum "$INSTALLED_OPERATOR" | awk '{print $1}')"
INSTALLED_DISPATCHER_SHA256="$(sha256sum "$INSTALLED_DISPATCHER" | awk '{print $1}')"
[[ "$INSTALLED_OPERATOR_SHA256" == "$EXPECTED_OPERATOR_SHA256" ]] || fail 'installed operator SHA256 mismatch'
[[ "$INSTALLED_DISPATCHER_SHA256" == "$DISPATCHER_SHA256" ]] || fail 'installed dispatcher SHA256 mismatch'
[[ "$(stat -c '%U:%G:%a' "$INSTALLED_OPERATOR")" == 'root:root:755' ]] || fail 'installed operator metadata mismatch'
[[ "$(stat -c '%U:%G:%a' "$INSTALLED_DISPATCHER")" == 'root:root:755' ]] || fail 'installed dispatcher metadata mismatch'
[[ "$(stat -c '%U:%G:%a' "$SUDOERS")" == 'root:root:440' ]] || fail 'sudoers metadata mismatch'
visudo -cf "$SUDOERS" >/dev/null

CONF_TMP="$(mktemp /etc/hermes-deals-audits.d/.issue-307-phase-c.conf.XXXXXX)"
cat > "$CONF_TMP" <<CONF
registered_commit='$EXPECTED_SHA'
operator_sha256='$INSTALLED_OPERATOR_SHA256'
dispatcher_sha256='$INSTALLED_DISPATCHER_SHA256'
runner_user='github-runner'
allowed_modes='check apply-dual verify-dual'
CONF
chown root:root "$CONF_TMP"
chmod 0644 "$CONF_TMP"
mv -f -- "$CONF_TMP" "$CONF"

SUDO_LIST="$(sudo -l -U github-runner)"
printf '%s\n' "$SUDO_LIST" | grep -Fq "$INSTALLED_DISPATCHER check" || fail 'check sudo authorization is missing'
printf '%s\n' "$SUDO_LIST" | grep -Fq "$INSTALLED_DISPATCHER apply-dual" || fail 'apply-dual sudo authorization is missing'
printf '%s\n' "$SUDO_LIST" | grep -Fq "$INSTALLED_DISPATCHER verify-dual" || fail 'verify-dual sudo authorization is missing'
if printf '%s\n' "$SUDO_LIST" | grep -Fq "$INSTALLED_DISPATCHER rollback-lan"; then
  fail 'rollback-lan must not be runner-authorized'
fi
RUNNER_HAS_DOCKER="$(id -nG github-runner | tr ' ' '\n' | grep -Fxq docker && echo true || echo false)"
[[ "$RUNNER_HAS_DOCKER" == false ]] || fail 'github-runner must not belong to docker group'

printf 'INSTALL_RESULT=PASS\n'
printf 'REGISTERED_COMMIT=%s\n' "$EXPECTED_SHA"
printf 'OPERATOR_SHA256=%s\n' "$INSTALLED_OPERATOR_SHA256"
printf 'DISPATCHER_SHA256=%s\n' "$INSTALLED_DISPATCHER_SHA256"
printf 'SUDOERS_VALID=true\n'
printf 'RUNNER_HAS_DOCKER_GROUP=false\n'
printf 'ALLOWED_MODES=check,apply-dual,verify-dual\n'
printf 'ROLLBACK_MODE_RUNNER_AUTHORIZED=false\n'
printf 'PRODUCTION_RUNTIME_CHANGED=false\n'
printf 'CLOUDFLARE_ROUTE_CHANGED=false\n'
printf 'UFW_CHANGED=false\n'
printf 'DATABASE_WRITE=false\n'
printf 'SHARED_CLOUDFLARED_LIFECYCLE=false\n'
