#!/usr/bin/env bash
set -Eeuo pipefail

readonly ROOT="/usr/local/lib/hermes-deals-origin-monitor-control"
readonly REGISTERED_SHA_FILE="${ROOT}/registered-sha"
readonly PACKAGE_ROOT="${ROOT}/packages"
readonly RUNTIME_DIR="/usr/local/lib/hermes-deals-origin-monitor"
readonly RUNNER_PATH="/usr/local/sbin/hermes-deals-origin-monitor-run"
readonly SERVICE_PATH="/etc/systemd/system/hermes-deals-origin-monitor.service"
readonly TIMER_PATH="/etc/systemd/system/hermes-deals-origin-monitor.timer"
readonly SERVICE_NAME="hermes-deals-origin-monitor.service"
readonly TIMER_NAME="hermes-deals-origin-monitor.timer"

fail() {
  printf 'ERROR: origin monitor control validation failed\n' >&2
  exit 1
}

[[ "$EUID" -eq 0 ]] || fail
[[ "$#" -eq 3 ]] || fail
mode="$1"
registered_sha="$2"
export_dir="$3"
[[ "$mode" == "preflight" || "$mode" == "install-disabled" ]] || fail
[[ "$registered_sha" =~ ^[0-9a-f]{40}$ ]] || fail
[[ "$export_dir" == /home/github-runner/_work/_temp/hermes-deals-origin-monitor-* ]] || fail
[[ -f "$REGISTERED_SHA_FILE" ]] || fail
[[ "$(cat "$REGISTERED_SHA_FILE")" == "$registered_sha" ]] || fail
package_dir="${PACKAGE_ROOT}/${registered_sha}"
[[ -d "$package_dir" ]] || fail

for required in \
  hermes_deals_origin_probe.py \
  hermes_deals_origin_monitor.py \
  origin-monitor-run.sh \
  hermes-deals-origin-monitor.service \
  hermes-deals-origin-monitor.timer \
  package.sha256; do
  [[ -f "${package_dir}/${required}" ]] || fail
done
(
  cd "$package_dir"
  sha256sum --check --strict package.sha256 >/dev/null
) || fail

active="$(systemctl is-active "$SERVICE_NAME" 2>/dev/null || true)"
timer_active="$(systemctl is-active "$TIMER_NAME" 2>/dev/null || true)"
enabled="$(systemctl is-enabled "$SERVICE_NAME" 2>/dev/null || true)"
timer_enabled="$(systemctl is-enabled "$TIMER_NAME" 2>/dev/null || true)"
[[ "$active" != "active" && "$timer_active" != "active" ]] || fail
[[ "$enabled" != "enabled" && "$timer_enabled" != "enabled" ]] || fail

install_performed=false
if [[ "$mode" == "install-disabled" ]]; then
  install -d -o root -g root -m 0755 "$RUNTIME_DIR"
  install -o root -g root -m 0644 "${package_dir}/hermes_deals_origin_probe.py" "${RUNTIME_DIR}/hermes_deals_origin_probe.py"
  install -o root -g root -m 0644 "${package_dir}/hermes_deals_origin_monitor.py" "${RUNTIME_DIR}/hermes_deals_origin_monitor.py"
  install -o root -g root -m 0755 "${package_dir}/origin-monitor-run.sh" "$RUNNER_PATH"
  install -o root -g root -m 0644 "${package_dir}/hermes-deals-origin-monitor.service" "$SERVICE_PATH"
  install -o root -g root -m 0644 "${package_dir}/hermes-deals-origin-monitor.timer" "$TIMER_PATH"
  python3 -m py_compile "${RUNTIME_DIR}/hermes_deals_origin_probe.py" "${RUNTIME_DIR}/hermes_deals_origin_monitor.py"
  bash -n "$RUNNER_PATH"
  systemctl daemon-reload
  [[ "$(systemctl is-active "$SERVICE_NAME" 2>/dev/null || true)" != "active" ]] || fail
  [[ "$(systemctl is-active "$TIMER_NAME" 2>/dev/null || true)" != "active" ]] || fail
  [[ "$(systemctl is-enabled "$SERVICE_NAME" 2>/dev/null || true)" != "enabled" ]] || fail
  [[ "$(systemctl is-enabled "$TIMER_NAME" 2>/dev/null || true)" != "enabled" ]] || fail
  install_performed=true
fi

install -d -o github-runner -g github-runner -m 0700 "$export_dir"
evidence_dir="${export_dir}/installation-evidence"
install -d -o github-runner -g github-runner -m 0700 "$evidence_dir"
cat > "${evidence_dir}/origin-monitor-installation.json" <<JSON
{"schema_version":"1","mode":"${mode}","registered_sha":"${registered_sha}","package_verified":true,"install_performed":${install_performed},"service_active":false,"timer_active":false,"service_enabled":false,"timer_enabled":false,"monitor_executed":false,"production_deploy":false,"application_restart":false,"database_read_write":false,"cloudflare_mutation":false,"b15m2_v08":false}
JSON
chown github-runner:github-runner "${evidence_dir}/origin-monitor-installation.json"
chmod 0600 "${evidence_dir}/origin-monitor-installation.json"
printf 'EVIDENCE_DIR=%s\n' "$evidence_dir"
