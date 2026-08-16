#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run with sudo"
[[ $# -eq 1 ]] || fail "usage: sudo bash tools/runner/install-aldi-new-baseline-weekly-shadow-dispatcher.sh <merged-commit-sha>"
EXPECTED_SHA="$1"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid merged commit SHA"

REPO='/home/andris/hermes-deals'
RUNNER_SERVICE='actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service'
LIBEXEC='/usr/local/libexec/hermes-deals-audits/aldi-new-baseline-weekly-shadow-v01'
DISPATCHER='/usr/local/sbin/hermes-deals-aldi-new-baseline-weekly-shadow-dispatch'
CONF='/etc/hermes-deals-audits.d/aldi-new-baseline-weekly-shadow.conf'
SUDOERS='/etc/sudoers.d/hermes-deals-aldi-new-baseline-weekly-shadow'
REQUEST_ROOT='/var/lib/hermes-deals/aldi-new-baseline-weekly-shadow-v01/requests'

declare -A source_files=(
  [bridge]='tools/aldi_new_baseline_weekly_shadow_bridge.py'
  [gate_a]='tools/aldi_new_immutable_baseline_gate.py'
  [gate_b]='tools/aldi_new_baseline_page_card_parity.py'
  [gate_c]='tools/aldi_new_baseline_gate_c_replay.py'
  [two_cycle]='tools/aldi_new_baseline_two_cycle_shadow_gate.py'
  [dispatcher]='tools/runner/aldi-new-baseline-weekly-shadow-dispatcher.sh'
)

for user in andris github-runner; do id "$user" >/dev/null 2>&1 || fail "required user missing: $user"; done
for command in awk bash git grep id install mktemp readlink rm sha256sum stat sudo systemctl visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command missing: $command"
done

REPO="$(readlink -f -- "$REPO")"
[[ "$REPO" == '/home/andris/hermes-deals' ]] || fail "repository path drift"
[[ -d "$REPO/.git" && ! -L "$REPO/.git" ]] || fail "repository missing or unsafe"
git_read() { GIT_OPTIONAL_LOCKS=0 git -C "$REPO" "$@"; }
[[ "$(git_read branch --show-current)" == main ]] || fail "repository is not on main"
[[ -z "$(git_read status --porcelain)" ]] || fail "repository is dirty"
[[ "$(git_read rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail "repository is not exact merged main"
origin="$(git_read remote get-url origin)"
case "$origin" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "origin is not allowlisted" ;;
esac

for key in "${!source_files[@]}"; do
  path="${source_files[$key]}"
  git_read cat-file -e "$EXPECTED_SHA:$path" || fail "registered file missing: $path"
done

tmp="$(mktemp -d /tmp/hermes-aldi-new-baseline-weekly-shadow-install.XXXXXX)"
cleanup() { rm -rf -- "$tmp"; }
trap cleanup EXIT

for key in bridge gate_a gate_b gate_c two_cycle dispatcher; do
  git_read show "$EXPECTED_SHA:${source_files[$key]}" > "$tmp/$key"
  [[ -s "$tmp/$key" ]] || fail "empty registered source: $key"
done
python3 -m py_compile "$tmp/bridge" "$tmp/gate_a" "$tmp/gate_b" "$tmp/gate_c" "$tmp/two_cycle"
bash -n "$tmp/dispatcher"

cat > "$tmp/sudoers" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-aldi-new-baseline-weekly-shadow-dispatch env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-aldi-new-baseline-weekly-shadow-dispatch
SUDOERS
chmod 0440 "$tmp/sudoers"
visudo -cf "$tmp/sudoers" >/dev/null

install -d -o root -g root -m 0755 /usr/local/libexec/hermes-deals-audits /etc/hermes-deals-audits.d
install -d -o root -g root -m 0755 "$LIBEXEC"
install -d -o root -g root -m 0700 /var/lib/hermes-deals/aldi-new-baseline-weekly-shadow-v01 "$REQUEST_ROOT"
install -d -o andris -g andris -m 0700 /home/andris/hermes-deals-runner-evidence

install -o root -g root -m 0555 "$tmp/bridge" "$LIBEXEC/aldi_new_baseline_weekly_shadow_bridge.py"
install -o root -g root -m 0444 "$tmp/gate_a" "$LIBEXEC/aldi_new_immutable_baseline_gate.py"
install -o root -g root -m 0444 "$tmp/gate_b" "$LIBEXEC/aldi_new_baseline_page_card_parity.py"
install -o root -g root -m 0444 "$tmp/gate_c" "$LIBEXEC/aldi_new_baseline_gate_c_replay.py"
install -o root -g root -m 0444 "$tmp/two_cycle" "$LIBEXEC/aldi_new_baseline_two_cycle_shadow_gate.py"
install -o root -g root -m 0755 "$tmp/dispatcher" "$DISPATCHER"
install -o root -g root -m 0440 "$tmp/sudoers" "$SUDOERS"

bridge_sha="$(sha256sum "$LIBEXEC/aldi_new_baseline_weekly_shadow_bridge.py" | awk '{print $1}')"
gate_a_sha="$(sha256sum "$LIBEXEC/aldi_new_immutable_baseline_gate.py" | awk '{print $1}')"
gate_b_sha="$(sha256sum "$LIBEXEC/aldi_new_baseline_page_card_parity.py" | awk '{print $1}')"
gate_c_sha="$(sha256sum "$LIBEXEC/aldi_new_baseline_gate_c_replay.py" | awk '{print $1}')"
two_cycle_sha="$(sha256sum "$LIBEXEC/aldi_new_baseline_two_cycle_shadow_gate.py" | awk '{print $1}')"

conf_tmp="$(mktemp /etc/hermes-deals-audits.d/.aldi-new-baseline-weekly-shadow.conf.XXXXXX)"
cat > "$conf_tmp" <<CONF
registered_main_sha='$EXPECTED_SHA'
request_root='$REQUEST_ROOT'
bridge_path='$LIBEXEC/aldi_new_baseline_weekly-shadow_bridge.py'
bridge_sha256='$bridge_sha'
gate_a_sha256='$gate_a_sha'
gate_b_sha256='$gate_b_sha'
gate_c_sha256='$gate_c_sha'
two_cycle_sha256='$two_cycle_sha'
CONF
chown root:root "$conf_tmp"
chmod 0644 "$conf_tmp"
mv -f -- "$conf_tmp" "$CONF"

visudo -cf "$SUDOERS" >/dev/null
systemctl is-active --quiet "$RUNNER_SERVICE" || fail "GitHub Actions runner service is not active"
sudo -l -U github-runner | grep -Fq "$DISPATCHER" || fail "github-runner dispatcher sudo rule missing"
runner_has_docker="$(id -nG github-runner | tr ' ' '\n' | grep -Fxq docker && echo true || echo false)"
[[ "$runner_has_docker" == false ]] || fail "github-runner must not belong to docker group"

printf 'INSTALL_RESULT=PASS\nREGISTERED_MAIN_SHA=%s\nBRIDGE_SHA256=%s\nGATE_A_SHA256=%s\nGATE_B_SHA256=%s\nGATE_C_SHA256=%s\nTWO_CYCLE_SHA256=%s\nSUDOERS_VALID=true\nRUNNER_HAS_DOCKER_GROUP=false\nPRODUCTION_DATABASE_WRITE=false\nREVIEW_PUBLICATION_WRITE=false\nSOURCE_MUTATION=false\nPRODUCTION_DEPLOYMENT=false\nSCHEDULER_ACTIVATION=false\n' \
  "$EXPECTED_SHA" "$bridge_sha" "$gate_a_sha" "$gate_b_sha" "$gate_c_sha" "$two_cycle_sha"
