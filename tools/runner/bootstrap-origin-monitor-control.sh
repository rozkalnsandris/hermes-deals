#!/usr/bin/env bash
set -Eeuo pipefail

readonly PRIMARY_WORKTREE="/home/andris/hermes-deals"
readonly CONTROL_ROOT="/usr/local/lib/hermes-deals-origin-monitor-control"
readonly PACKAGE_ROOT="${CONTROL_ROOT}/packages"
readonly CONTROL_PATH="/usr/local/sbin/hermes-deals-origin-monitor-control"
readonly SUDOERS_PATH="/etc/sudoers.d/hermes-deals-origin-monitor-control"

fail() {
  printf 'ERROR: origin monitor bootstrap validation failed\n' >&2
  exit 1
}

[[ "$EUID" -eq 0 ]] || fail
[[ "$#" -eq 2 ]] || fail
source_worktree="$(realpath "$1")"
registered_sha="$2"
[[ "$registered_sha" =~ ^[0-9a-f]{40}$ ]] || fail
[[ "$source_worktree" != "$PRIMARY_WORKTREE" ]] || { printf 'primary production worktree is forbidden\n' >&2; exit 1; }
[[ -d "${source_worktree}/.git" || -f "${source_worktree}/.git" ]] || fail
[[ "$(git -C "$source_worktree" rev-parse HEAD)" == "$registered_sha" ]] || fail
[[ "$(git -C "$source_worktree" symbolic-ref -q HEAD || true)" == "" ]] || { printf 'source worktree must be detached\n' >&2; exit 1; }
[[ -z "$(git -C "$source_worktree" status --porcelain=v1 --untracked-files=all)" ]] || { printf 'source worktree is not clean\n' >&2; exit 1; }
git -C "$source_worktree" merge-base --is-ancestor "$registered_sha" origin/main || fail

required=(
  tools/hermes_deals_origin_probe.py
  tools/hermes_deals_origin_monitor.py
  tools/runner/origin-monitor-run.sh
  tools/runner/origin-monitor-control.sh
  deploy/systemd/hermes-deals-origin-monitor.service
  deploy/systemd/hermes-deals-origin-monitor.timer
)
for path in "${required[@]}"; do
  [[ -f "${source_worktree}/${path}" ]] || fail
done
python3 -m py_compile \
  "${source_worktree}/tools/hermes_deals_origin_probe.py" \
  "${source_worktree}/tools/hermes_deals_origin_monitor.py"
bash -n "${source_worktree}/tools/runner/origin-monitor-run.sh"
bash -n "${source_worktree}/tools/runner/origin-monitor-control.sh"

package_dir="${PACKAGE_ROOT}/${registered_sha}"
install -d -o root -g root -m 0755 "$CONTROL_ROOT" "$PACKAGE_ROOT" "$package_dir"
install -o root -g root -m 0644 "${source_worktree}/tools/hermes_deals_origin_probe.py" "${package_dir}/hermes_deals_origin_probe.py"
install -o root -g root -m 0644 "${source_worktree}/tools/hermes_deals_origin_monitor.py" "${package_dir}/hermes_deals_origin_monitor.py"
install -o root -g root -m 0755 "${source_worktree}/tools/runner/origin-monitor-run.sh" "${package_dir}/origin-monitor-run.sh"
install -o root -g root -m 0644 "${source_worktree}/deploy/systemd/hermes-deals-origin-monitor.service" "${package_dir}/hermes-deals-origin-monitor.service"
install -o root -g root -m 0644 "${source_worktree}/deploy/systemd/hermes-deals-origin-monitor.timer" "${package_dir}/hermes-deals-origin-monitor.timer"
(
  cd "$package_dir"
  sha256sum \
    hermes_deals_origin_probe.py \
    hermes_deals_origin_monitor.py \
    origin-monitor-run.sh \
    hermes-deals-origin-monitor.service \
    hermes-deals-origin-monitor.timer > package.sha256
)
chmod 0644 "${package_dir}/package.sha256"
printf '%s\n' "$registered_sha" > "${CONTROL_ROOT}/registered-sha"
chmod 0644 "${CONTROL_ROOT}/registered-sha"
install -o root -g root -m 0755 "${source_worktree}/tools/runner/origin-monitor-control.sh" "$CONTROL_PATH"

cat > "$SUDOERS_PATH" <<'SUDOERS'
Cmnd_Alias HERMES_DEALS_ORIGIN_MONITOR_CONTROL = /usr/local/sbin/hermes-deals-origin-monitor-control *
github-runner ALL=(root) NOPASSWD: HERMES_DEALS_ORIGIN_MONITOR_CONTROL
SUDOERS
chmod 0440 "$SUDOERS_PATH"
visudo -cf "$SUDOERS_PATH" >/dev/null

printf 'REGISTERED_SHA=%s\n' "$registered_sha"
printf 'CONTROL_INSTALLED=true\n'
printf 'MONITOR_RUNTIME_INSTALLED=false\n'
printf 'MONITOR_ENABLED=false\n'
printf 'MONITOR_EXECUTED=false\n'
