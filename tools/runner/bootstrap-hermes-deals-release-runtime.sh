#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "bootstrap must run as root"
[[ $# -eq 1 ]] || fail "usage: bootstrap-hermes-deals-release-runtime.sh <exact-current-main-sha>"
EXPECTED_SHA="$1"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "expected SHA must be exact lowercase 40-character hex"

REPOSITORY='rozkalnsandris/hermes-deals'
REPOSITORY_URL='https://github.com/rozkalnsandris/hermes-deals'
PRIMARY='/home/andris/hermes-deals'
WORKTREE_PARENT='/home/andris/hermes-deals-worktrees'
SOURCE="$WORKTREE_PARENT/release-control"
RUNNER_USER='github-release-runner'
RUNNER_HOME='/home/github-release-runner'
RUNNER_DIR="$RUNNER_HOME/actions-runner"
RUNNER_NAME='rpi5-hermes-deals-release'
RUNNER_LABEL='hermes-deals-release'
RUNNER_SERVICE='actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-release.service'
TOKEN_DIR='/etc/hermes-deals-release-bridge'
TOKEN_FILE="$TOKEN_DIR/token"
STATE_DIR='/var/lib/hermes-deals-release-bridge'
BRIDGE='/usr/local/sbin/hermes-deals-release-bridge'
AUTO_REGISTER='/usr/local/sbin/hermes-deals-release-auto-register'
SUDOERS='/etc/sudoers.d/hermes-deals-release-bridge'
HERMES_SCRIPT='/home/andris/.hermes/scripts/hermes-deals-release-bridge.sh'
HERMES_JOB='hermes-deals-release-bridge'

for command in awk bash chown curl find git gh grep id install mktemp mv python3 readlink rm runuser sha256sum stat sudo systemctl tar tr useradd visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
id andris >/dev/null 2>&1 || fail "required account andris is missing"
[[ -d "$PRIMARY" && ! -L "$PRIMARY" ]] || fail "primary repository is missing or unsafe"
[[ -n "${HERMES_GITHUB_TOKEN:-}" ]] || fail "HERMES_GITHUB_TOKEN must be passed through sudo environment"
BRIDGE_TOKEN="$HERMES_GITHUB_TOKEN"
unset HERMES_GITHUB_TOKEN
[[ "$BRIDGE_TOKEN" =~ ^(github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,})$ ]] || fail "HERMES_GITHUB_TOKEN format is invalid"

install -d -o root -g root -m 0700 "$TOKEN_DIR" "$STATE_DIR"
TOKEN_TMP="$(mktemp "$TOKEN_DIR/.token.XXXXXX")"
printf '%s\n' "$BRIDGE_TOKEN" > "$TOKEN_TMP"
unset BRIDGE_TOKEN
chown root:root "$TOKEN_TMP"
chmod 0600 "$TOKEN_TMP"
mv -f -- "$TOKEN_TMP" "$TOKEN_FILE"
TOKEN_VALIDATED=false
cleanup_token() {
  if [[ "$TOKEN_VALIDATED" != true ]]; then
    rm -f -- "$TOKEN_FILE"
  fi
}
trap cleanup_token EXIT

runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$PRIMARY" fetch --prune origin main
[[ "$(runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$PRIMARY" rev-parse refs/remotes/origin/main)" == "$EXPECTED_SHA" ]] || fail "origin/main does not equal the authorized bootstrap SHA"

python3 - "$TOKEN_FILE" "$REPOSITORY" <<'PY'
import json
import pathlib
import sys
import urllib.request

token_path, repo = sys.argv[1:]
token = pathlib.Path(token_path).read_text(encoding="utf-8").strip()
headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "User-Agent": "hermes-deals-release-bootstrap",
    "X-GitHub-Api-Version": "2022-11-28",
}

def request(method: str, url: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read()
        return None if not body else json.loads(body)

user = request("GET", "https://api.github.com/user")
if user.get("login") != "rozkalnsandris" or int(user.get("id") or 0) != 277435981:
    raise SystemExit("persistent bridge token is not owned by the allowlisted owner")
repo_data = request("GET", f"https://api.github.com/repos/{repo}")
if repo_data.get("full_name") != repo:
    raise SystemExit("persistent bridge token cannot read the target repository")
labels = {
    "hermes:deploy-ready": ("1d76db", "Validated release request awaiting Hermes"),
    "hermes:deploy-running": ("fbca04", "Hermes release workflow is active"),
    "hermes:deploy-pass": ("0e8a16", "Hermes release completed successfully"),
    "hermes:deploy-fail": ("d1242f", "Hermes release workflow failed"),
    "hermes:deploy-blocked": ("5319e7", "Hermes release request failed closed"),
}
existing = request("GET", f"https://api.github.com/repos/{repo}/labels?per_page=100")
names = {item.get("name") for item in existing}
for name, (color, description) in labels.items():
    if name not in names:
        request(
            "POST",
            f"https://api.github.com/repos/{repo}/labels",
            {"name": name, "color": color, "description": description},
        )
PY
TOKEN_VALIDATED=true
trap - EXIT

if ! id "$RUNNER_USER" >/dev/null 2>&1; then
  useradd --create-home --home-dir "$RUNNER_HOME" --shell /bin/bash "$RUNNER_USER"
fi
if id -nG "$RUNNER_USER" | tr ' ' '\n' | grep -Fxq docker; then
  fail "$RUNNER_USER must not belong to docker group"
fi
install -d -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0750 "$RUNNER_DIR"

if [[ ! -f "$RUNNER_DIR/.runner" ]]; then
  [[ -z "$(find "$RUNNER_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]] || fail "runner directory is non-empty but not configured"
  mapfile -d '' -t RUNNER_META < <(python3 <<'PY'
import json
import urllib.request

request = urllib.request.Request(
    "https://api.github.com/repos/actions/runner/releases/latest",
    headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "hermes-deals-release-bootstrap",
        "X-GitHub-Api-Version": "2022-11-28",
    },
)
with urllib.request.urlopen(request, timeout=30) as response:
    release = json.load(response)
assets = [
    asset for asset in release.get("assets", [])
    if str(asset.get("name", "")).startswith("actions-runner-linux-arm64-")
    and str(asset.get("name", "")).endswith(".tar.gz")
]
if len(assets) != 1:
    raise SystemExit("expected exactly one latest Linux ARM64 runner asset")
asset = assets[0]
digest = str(asset.get("digest") or "")
if not digest.startswith("sha256:") or len(digest) != 71:
    raise SystemExit("runner asset has no immutable SHA256 digest")
for value in (str(asset["name"]), str(asset["browser_download_url"]), digest.removeprefix("sha256:")):
    print(value, end="\0")
PY
  )
  [[ ${#RUNNER_META[@]} -eq 3 ]] || fail "runner release metadata is incomplete"
  ARCHIVE="$(mktemp /tmp/actions-runner-linux-arm64.XXXXXX.tar.gz)"
  cleanup_archive() { rm -f -- "$ARCHIVE"; }
  trap cleanup_archive EXIT
  curl --fail --location --silent --show-error --output "$ARCHIVE" "${RUNNER_META[1]}"
  [[ "$(sha256sum "$ARCHIVE" | awk '{print $1}')" == "${RUNNER_META[2]}" ]] || fail "GitHub Actions runner archive digest mismatch"
  tar --extract --gzip --file "$ARCHIVE" --directory "$RUNNER_DIR" --no-same-owner
  chown -R "$RUNNER_USER:$RUNNER_USER" "$RUNNER_DIR"
  rm -f -- "$ARCHIVE"
  trap - EXIT
  "$RUNNER_DIR/bin/installdependencies.sh"
  REGISTRATION_TOKEN="$(runuser -u andris -- env HOME=/home/andris gh api --method POST "repos/$REPOSITORY/actions/runners/registration-token" --jq .token)"
  [[ "$REGISTRATION_TOKEN" =~ ^[A-Za-z0-9]+$ ]] || fail "runner registration token generation failed"
  runuser -u "$RUNNER_USER" -- env HOME="$RUNNER_HOME" "$RUNNER_DIR/config.sh" \
    --url "$REPOSITORY_URL" \
    --token "$REGISTRATION_TOKEN" \
    --name "$RUNNER_NAME" \
    --labels "$RUNNER_LABEL" \
    --work _work \
    --unattended \
    --replace
fi

python3 - "$RUNNER_DIR/.runner" "$RUNNER_NAME" <<'PY'
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if data.get("agentName") != sys.argv[2]:
    raise SystemExit("configured runner name mismatch")
if str(data.get("gitHubUrl", "")).rstrip("/") != "https://github.com/rozkalnsandris/hermes-deals":
    raise SystemExit("configured runner repository mismatch")
PY

if ! systemctl list-unit-files "$RUNNER_SERVICE" --no-legend 2>/dev/null | grep -Fq "$RUNNER_SERVICE"; then
  (cd "$RUNNER_DIR" && ./svc.sh install "$RUNNER_USER")
fi
(cd "$RUNNER_DIR" && ./svc.sh start)
systemctl is-active --quiet "$RUNNER_SERVICE" || fail "release runner service is not active"

install -d -o andris -g andris -m 0750 "$WORKTREE_PARENT"
if [[ ! -e "$SOURCE" ]]; then
  runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$PRIMARY" worktree add --detach "$SOURCE" "$EXPECTED_SHA"
else
  [[ -d "$SOURCE" && ! -L "$SOURCE" ]] || fail "release-control worktree path is unsafe"
  [[ "$(stat -c '%U:%G' "$SOURCE")" == 'andris:andris' ]] || fail "release-control worktree ownership is invalid"
  [[ -z "$(runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$SOURCE" status --porcelain=v1 --untracked-files=all)" ]] || fail "release-control worktree is not clean"
  runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$SOURCE" checkout --detach "$EXPECTED_SHA" >/dev/null
fi
[[ "$(runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$SOURCE" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail "release-control worktree SHA mismatch"
[[ -z "$(runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$SOURCE" branch --show-current)" ]] || fail "release-control worktree must remain detached"

bash "$SOURCE/tools/runner/install-rpi5-release-dispatcher.sh"
SOURCE_BRIDGE="$SOURCE/tools/runner/release/hermes-deals-release-bridge"
SOURCE_AUTO="$SOURCE/tools/runner/release/hermes-deals-release-auto-register"
for source_file in "$SOURCE_BRIDGE" "$SOURCE_AUTO"; do
  [[ -f "$source_file" && ! -L "$source_file" ]] || fail "bridge source is missing or unsafe: $source_file"
done
python3 - "$SOURCE_BRIDGE" <<'PY'
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
compile(path.read_text(encoding="utf-8"), str(path), "exec")
PY
bash -n "$SOURCE_AUTO"
install -o root -g root -m 0755 "$SOURCE_BRIDGE" "$BRIDGE"
install -o root -g root -m 0755 "$SOURCE_AUTO" "$AUTO_REGISTER"

SUDOERS_TMP="$(mktemp /tmp/hermes-deals-release-bridge-sudoers.XXXXXX)"
cleanup_sudoers() { rm -f -- "$SUDOERS_TMP"; }
trap cleanup_sudoers EXIT
cat > "$SUDOERS_TMP" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-release-bridge env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
andris ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-release-bridge poll
SUDOERS
chmod 0440 "$SUDOERS_TMP"
visudo -cf "$SUDOERS_TMP" >/dev/null
install -o root -g root -m 0440 "$SUDOERS_TMP" "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null
rm -f -- "$SUDOERS_TMP"
trap - EXIT

install -d -o andris -g andris -m 0700 /home/andris/.hermes/scripts
SCRIPT_TMP="$(mktemp /tmp/hermes-deals-release-bridge-script.XXXXXX)"
cat > "$SCRIPT_TMP" <<'SCRIPT'
#!/usr/bin/env bash
set -Eeuo pipefail
output="$(sudo --non-interactive /usr/local/sbin/hermes-deals-release-bridge poll)"
if [[ -n "$output" ]]; then
  printf '%s\n' "$output"
fi
SCRIPT
install -o andris -g andris -m 0700 "$SCRIPT_TMP" "$HERMES_SCRIPT"
rm -f -- "$SCRIPT_TMP"

HERMES_BIN="$(runuser -u andris -- env HOME=/home/andris bash -lc 'command -v hermes')"
[[ -x "$HERMES_BIN" ]] || fail "Hermes CLI is not available for user andris"
HERMES_LIST="$(runuser -u andris -- env HOME=/home/andris "$HERMES_BIN" cron list 2>&1 || true)"
if ! grep -Fq "$HERMES_JOB" <<<"$HERMES_LIST"; then
  runuser -u andris -- env HOME=/home/andris "$HERMES_BIN" cron create "every 5m" \
    --no-agent \
    --script "$(basename "$HERMES_SCRIPT")" \
    --deliver telegram \
    --name "$HERMES_JOB"
fi
runuser -u andris -- env HOME=/home/andris "$HERMES_BIN" cron status >/dev/null

sudo -l -U andris | grep -Fq '/usr/local/sbin/hermes-deals-release-bridge poll' || fail "Hermes bridge sudo rule is missing"
if sudo -l -U andris | grep -Fq '/usr/local/sbin/hermes-deals-release-auto-register'; then
  fail "root-only auto-register leaked into sudo rules"
fi
if id -nG "$RUNNER_USER" | tr ' ' '\n' | grep -Fxq docker; then
  fail "$RUNNER_USER unexpectedly belongs to docker group"
fi

printf 'BOOTSTRAP_RESULT=PASS\nSOURCE_SHA=%s\nRUNNER_SERVICE=%s\nRUNNER_HAS_DOCKER_GROUP=false\nRELEASE_DISPATCHER_INSTALLED=true\nHERMES_BRIDGE_INSTALLED=true\nHERMES_CRON_JOB=%s\nHERMES_NO_AGENT=true\nDATABASE_WRITES_AUTHORIZED=false\n' \
  "$EXPECTED_SHA" "$RUNNER_SERVICE" "$HERMES_JOB"
