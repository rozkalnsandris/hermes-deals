#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


TARGET_SHA = "128325461f249791af8a5653163772e955dd2b89"

BASELINE_OLD = '''  [[ "$API_IMAGE_TAG" == hermes-deals-api:release-* ]] || fail 'current_api_tag_not_release_managed'
  [[ "$API_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || fail 'current_api_image_id_invalid'
  [[ "$API_REVISION" =~ ^[0-9a-f]{40}$ ]] || fail 'current_api_revision_invalid'
  [[ "$WEB_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || fail 'current_web_image_id_invalid'
'''

BASELINE_NEW = '''  [[ "$API_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || fail 'current_api_image_id_invalid'
  [[ "$API_REVISION" =~ ^[0-9a-f]{40}$ ]] || fail 'current_api_revision_invalid'
  [[ "$WEB_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || fail 'current_web_image_id_invalid'
  if [[ "$API_IMAGE_TAG" =~ ^hermes-deals-api:main-([0-9a-f]{12})$ ]]; then
    [[ "${BASH_REMATCH[1]}" == "${API_REVISION:0:12}" ]] \\
      || fail 'current_api_main_tag_revision_mismatch'
  elif [[ "$API_IMAGE_TAG" =~ ^hermes-deals-api:release-[A-Za-z0-9_.-]+$ ]]; then
    :
  else
    fail 'current_api_tag_not_release_managed'
  fi
'''

ROLLBACK_OLD = '''if not values[0].startswith("hermes-deals-api:release-"):
    raise SystemExit(2)
for idx in (1,3):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", values[idx]):
        raise SystemExit(2)
if not re.fullmatch(r"[0-9a-f]{40}", values[2]):
    raise SystemExit(2)
'''

ROLLBACK_NEW = '''tag = values[0]
main_tag = re.fullmatch(r"hermes-deals-api:main-([0-9a-f]{12})", tag)
legacy_release = re.fullmatch(r"hermes-deals-api:release-[A-Za-z0-9_.-]+", tag)
if main_tag is None and legacy_release is None:
    raise SystemExit(2)
for idx in (1,3):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", values[idx]):
        raise SystemExit(2)
if not re.fullmatch(r"[0-9a-f]{40}", values[2]):
    raise SystemExit(2)
if main_tag is not None and not values[2].startswith(main_tag.group(1)):
    raise SystemExit(2)
'''

COMMANDS_OLD = '''for command in curl docker flock grep install python3 sha256sum stat systemctl; do
'''

COMMANDS_NEW = '''for command in curl docker flock grep install python3 runuser sha256sum stat systemctl; do
'''

GIT_STATE_OLD = '''primary_state() {
  printf '%s\\n' \\
    "$(git -C "$PRIMARY" rev-parse HEAD)" \\
    "$(git -C "$PRIMARY" branch --show-current)" \\
    "$(git -C "$PRIMARY" status --porcelain=v1 --untracked-files=all)" \\
    "$(git -C "$PRIMARY" diff --cached --binary)" |
    sha256sum | awk '{print $1}'
}
'''

GIT_STATE_NEW = '''primary_git() {
  runuser -u andris -- git -C "$PRIMARY" "$@"
}

primary_state() {
  printf '%s\\n' \\
    "$(primary_git rev-parse HEAD)" \\
    "$(primary_git branch --show-current)" \\
    "$(primary_git status --porcelain=v1 --untracked-files=all)" \\
    "$(primary_git diff --cached --binary --no-ext-diff --no-textconv)" |
    sha256sum | awk '{print $1}'
}
'''

COMPOSE_STDIN_HEAD_OLD = '''  compose "$api_tag" "$ui_mode" "$nginx_config" config --format json |
    python3 - "$api_tag" "$ui_mode" "$nginx_config" <<'PY'
'''

COMPOSE_STDIN_HEAD_NEW = '''  compose "$api_tag" "$ui_mode" "$nginx_config" config --format json |
    python3 -c '
'''

COMPOSE_STDIN_TAIL_OLD = '''if not db:
    raise SystemExit("database service missing from model")
PY
}
'''

COMPOSE_STDIN_TAIL_NEW = '''if not db:
    raise SystemExit("database service missing from model")
' "$api_tag" "$ui_mode" "$nginx_config"
}
'''

SOURCE_CONTRACT_OLD = '''target_without_mode = [line for line in target if "HERMES_UI_ASSET_MODE:" not in line]
if target_without_mode != primary:
    raise SystemExit("target base Compose differs from production baseline beyond W4B mode")
'''

SOURCE_CONTRACT_NEW = '''target_without_mode = [line for line in target if "HERMES_UI_ASSET_MODE:" not in line]
if primary != target and primary != target_without_mode:
    raise SystemExit("target base Compose differs from reviewed W4B source states")
'''

INLINE_RETURN_TRAP = "  trap 'rm -f \"$body\" \"$headers\"' RETURN\n"
HASHED_RETURN_TRAP = (
    "  trap 'rm -f \"$body\" \"$headers\" \"$js_headers\" \"$css_headers\" "
    "\"$js_body\" \"$css_body\"' RETURN\n"
)


def replace_exact_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label} replacement expected exactly once, found {count}")
    return source.replace(old, new, 1)


def replace_assertion_cleanup_scope(
    source: str,
    *,
    name: str,
    next_name: str,
    return_trap: str,
) -> str:
    head = f"{name}() {{\n"
    end_marker = f"}}\n\n{next_name}() {{\n"
    exit_trap = return_trap.replace(" RETURN\n", " EXIT\n")

    source = replace_exact_once(
        source,
        head,
        f"{name}() (\n",
        f"{name} subshell head",
    )
    source = replace_exact_once(
        source,
        return_trap,
        exit_trap,
        f"{name} cleanup trap",
    )
    source = replace_exact_once(
        source,
        end_marker,
        f")\n\n{next_name}() {{\n",
        f"{name} subshell tail",
    )
    return source


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: render-hermes-deals-w4b-operator.py <template> <output>")

    template = Path(sys.argv[1])
    output = Path(sys.argv[2])
    if not template.is_file() or template.is_symlink():
        raise SystemExit("operator template is missing or unsafe")

    source = template.read_text(encoding="utf-8")
    if f"TARGET_SHA='{TARGET_SHA}'" not in source:
        raise SystemExit("operator target SHA drift")

    rendered = replace_exact_once(
        source,
        BASELINE_OLD,
        BASELINE_NEW,
        "managed-image baseline",
    )
    rendered = replace_exact_once(
        rendered,
        ROLLBACK_OLD,
        ROLLBACK_NEW,
        "rollback-state image validation",
    )
    rendered = replace_exact_once(
        rendered,
        COMMANDS_OLD,
        COMMANDS_NEW,
        "operator command allowlist",
    )
    rendered = replace_exact_once(
        rendered,
        GIT_STATE_OLD,
        GIT_STATE_NEW,
        "production Git state",
    )
    rendered = replace_exact_once(
        rendered,
        COMPOSE_STDIN_HEAD_OLD,
        COMPOSE_STDIN_HEAD_NEW,
        "Compose validator stdin head",
    )
    rendered = replace_exact_once(
        rendered,
        COMPOSE_STDIN_TAIL_OLD,
        COMPOSE_STDIN_TAIL_NEW,
        "Compose validator stdin tail",
    )
    rendered = replace_exact_once(
        rendered,
        SOURCE_CONTRACT_OLD,
        SOURCE_CONTRACT_NEW,
        "reviewed Compose source-state contract",
    )
    rendered = replace_assertion_cleanup_scope(
        rendered,
        name="assert_inline_w3",
        next_name="assert_hashed_w4",
        return_trap=INLINE_RETURN_TRAP,
    )
    rendered = replace_assertion_cleanup_scope(
        rendered,
        name="assert_hashed_w4",
        next_name="assert_target_runtime",
        return_trap=HASHED_RETURN_TRAP,
    )

    if BASELINE_OLD in rendered or ROLLBACK_OLD in rendered:
        raise SystemExit("stale W4B image validator remains after rendering")
    if COMMANDS_OLD in rendered or GIT_STATE_OLD in rendered:
        raise SystemExit("stale W4B production Git state path remains after rendering")
    if COMPOSE_STDIN_HEAD_OLD in rendered or COMPOSE_STDIN_TAIL_OLD in rendered:
        raise SystemExit("stale W4B Compose validator stdin path remains after rendering")
    if SOURCE_CONTRACT_OLD in rendered:
        raise SystemExit("stale W4B Compose source-state contract remains after rendering")
    if SOURCE_CONTRACT_NEW not in rendered:
        raise SystemExit("reviewed W4B Compose source-state marker mismatch")
    if COMPOSE_STDIN_HEAD_NEW not in rendered:
        raise SystemExit("Compose validator python -c marker mismatch")
    if rendered.count("current_api_main_tag_revision_mismatch") != 1:
        raise SystemExit("managed-main revision binding marker mismatch")
    if rendered.count('hermes-deals-api:main-([0-9a-f]{12})') != 2:
        raise SystemExit("managed-main tag validation marker mismatch")
    if rendered.count('runuser -u andris -- git -C "$PRIMARY" "$@"') != 1:
        raise SystemExit("production Git owner-identity marker mismatch")
    if rendered.count("data = json.load(sys.stdin)") != 1:
        raise SystemExit("Compose validator stdin JSON marker mismatch")
    if INLINE_RETURN_TRAP in rendered or HASHED_RETURN_TRAP in rendered:
        raise SystemExit("stale W4B RETURN cleanup trap remains after rendering")
    if rendered.count("assert_inline_w3() (\n") != 1:
        raise SystemExit("inline W3 assertion subshell marker mismatch")
    if rendered.count("assert_hashed_w4() (\n") != 1:
        raise SystemExit("hashed W4 assertion subshell marker mismatch")
    if rendered.count(INLINE_RETURN_TRAP.replace(" RETURN\n", " EXIT\n")) != 1:
        raise SystemExit("inline W3 EXIT cleanup trap marker mismatch")
    if rendered.count(HASHED_RETURN_TRAP.replace(" RETURN\n", " EXIT\n")) != 1:
        raise SystemExit("hashed W4 EXIT cleanup trap marker mismatch")
    if "safe.directory" in rendered:
        raise SystemExit("safe.directory bypass is forbidden")

    output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
