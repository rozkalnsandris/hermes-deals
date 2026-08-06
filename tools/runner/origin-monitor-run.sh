#!/usr/bin/env bash
set -Eeuo pipefail

readonly RUNTIME_DIR="/usr/local/lib/hermes-deals-origin-monitor"
readonly STATE_DIR="/var/lib/hermes-deals-origin-monitor"
readonly REPORT_DIR="${STATE_DIR}/reports"
readonly SUMMARY_PATH="${STATE_DIR}/latest-summary.json"
readonly PROBE="${RUNTIME_DIR}/hermes_deals_origin_probe.py"
readonly MONITOR="${RUNTIME_DIR}/hermes_deals_origin_monitor.py"
readonly PUBLIC_URL="https://deals.rozkalns.net"
readonly ORIGIN_URL="http://192.168.0.180:9128"
readonly ORIGIN_HOST="deals.rozkalns.net"
readonly WINDOW_SIZE=5
readonly MIN_SAMPLES=3
readonly ALERT_THRESHOLD=3
readonly RETENTION_COUNT=20

fail() {
  printf 'ERROR: origin monitor runtime validation failed\n' >&2
  exit 3
}

[[ "$(id -u)" -ne 0 ]] || fail
[[ -f "$PROBE" && -f "$MONITOR" ]] || fail
[[ "$(stat -c '%a' "$STATE_DIR")" == "700" ]] || fail
install -d -m 0700 "$REPORT_DIR"

as_of="$(TZ=Europe/Berlin date +%F)"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
report_tmp="${REPORT_DIR}/.probe-${stamp}.$$"
report_path="${REPORT_DIR}/probe-${stamp}.json"
summary_tmp="${STATE_DIR}/.summary-${stamp}.$$"
trap 'rm -f "$report_tmp" "$summary_tmp"' EXIT

set +e
python3 "$PROBE" \
  --public-base-url "$PUBLIC_URL" \
  --origin-base-url "$ORIGIN_URL" \
  --origin-host "$ORIGIN_HOST" \
  --as-of "$as_of" \
  --timeout 5 \
  --output "$report_tmp" >/dev/null
probe_rc=$?
set -e
[[ "$probe_rc" -ge 0 && "$probe_rc" -le 2 ]] || fail
[[ -s "$report_tmp" ]] || fail
chmod 0600 "$report_tmp"
mv -f "$report_tmp" "$report_path"
chmod 0600 "$report_path"

mapfile -d '' reports < <(
  find "$REPORT_DIR" -maxdepth 1 -type f -name 'probe-*.json' -print0 | sort -z
)
while (( ${#reports[@]} > RETENTION_COUNT )); do
  rm -f -- "${reports[0]}"
  reports=("${reports[@]:1}")
done
(( ${#reports[@]} >= 1 )) || fail

args=()
for report in "${reports[@]}"; do
  args+=(--input "$report")
done

set +e
python3 "$MONITOR" \
  "${args[@]}" \
  --window-size "$WINDOW_SIZE" \
  --min-samples "$MIN_SAMPLES" \
  --alert-threshold "$ALERT_THRESHOLD" \
  --output "$summary_tmp" >/dev/null
monitor_rc=$?
set -e
[[ "$monitor_rc" -ge 0 && "$monitor_rc" -le 2 ]] || fail
[[ -s "$summary_tmp" ]] || fail
chmod 0600 "$summary_tmp"
mv -f "$summary_tmp" "$SUMMARY_PATH"
chmod 0600 "$SUMMARY_PATH"

printf 'ORIGIN_MONITOR_STATE_WRITTEN=true\n'
printf 'ORIGIN_MONITOR_PROBE_EXIT=%s\n' "$probe_rc"
printf 'ORIGIN_MONITOR_POLICY_EXIT=%s\n' "$monitor_rc"
exit "$monitor_rc"
