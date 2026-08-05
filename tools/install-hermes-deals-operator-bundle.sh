#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

PRIMARY='/home/andris/hermes-deals'
SOURCE="$PRIMARY/config/hermes/hermes-deals-operator.yaml"
SKILL_ROOT="$PRIMARY/.agents/skills"
DEST_DIR="${HOME}/.hermes/skill-bundles"
DEST="$DEST_DIR/hermes-deals-operator.yaml"

[[ "$(id -un)" == 'andris' ]] || fail 'run as the andris user, not root'
[[ "$(pwd -P)" == "$PRIMARY" ]] || fail "run from $PRIMARY"
[[ -f "$SOURCE" && ! -L "$SOURCE" ]] || fail 'bundle template is missing or unsafe'
[[ -f "$SKILL_ROOT/hermes-deals-release/SKILL.md" ]] || fail 'hermes-deals-release skill is missing'
command -v hermes >/dev/null 2>&1 || fail 'hermes command is missing'

mkdir -p "$DEST_DIR"
chmod 0700 "$DEST_DIR"

if [[ -e "$DEST" ]]; then
  [[ -f "$DEST" && ! -L "$DEST" ]] || fail 'existing bundle destination is unsafe'
  backup="${DEST}.backup-$(date +%Y%m%d-%H%M%S)"
  cp -a -- "$DEST" "$backup"
  printf 'BUNDLE_BACKUP=%s\n' "$backup"
fi

install -m 0600 -- "$SOURCE" "$DEST"
hermes bundles reload >/dev/null
hermes bundles show hermes-deals-operator >/dev/null

SKILLS_OUTPUT="$(hermes skills list)"
for skill in github-auth hermes-deals-release; do
  grep -Fq -- "$skill" <<<"$SKILLS_OUTPUT" \
    || fail "required skill is not visible: $skill"
done

printf 'BUNDLE_INSTALL_RESULT=PASS\n'
printf 'BUNDLE_PATH=%s\n' "$DEST"
printf 'BUNDLE_COMMAND=/hermes-deals-operator\n'
printf 'OPERATOR_ROLE=deploy-only\n'
printf 'DATABASE_WRITES_AUTHORIZED=false\n'
printf 'PRODUCTION_CHANGED=false\n'
