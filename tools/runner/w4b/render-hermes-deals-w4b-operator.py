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

SOURCE_CONTRACT_OLD = '''primary = primary_base.read_text(encoding="utf-8").splitlines()
target = target_base.read_text(encoding="utf-8").splitlines()
mode_lines = [line for line in target if "HERMES_UI_ASSET_MODE:" in line]
if mode_lines != ["      HERMES_UI_ASSET_MODE: ${HERMES_UI_ASSET_MODE:-inline-w3}"]:
    raise SystemExit("unexpected W4B Compose mode line")
target_without_mode = [line for line in target if "HERMES_UI_ASSET_MODE:" not in line]
if target_without_mode != primary:
    raise SystemExit("target base Compose differs from production baseline beyond W4B mode")
'''

SOURCE_CONTRACT_NEW = '''primary = primary_base.read_text(encoding="utf-8").splitlines()
target = target_base.read_text(encoding="utf-8").splitlines()
mode_line = "      HERMES_UI_ASSET_MODE: ${HERMES_UI_ASSET_MODE:-inline-w3}"
target_mode_lines = [line for line in target if "HERMES_UI_ASSET_MODE:" in line]
if target_mode_lines != [mode_line]:
    raise SystemExit("unexpected W4B Compose mode line")
primary_mode_lines = [line for line in primary if "HERMES_UI_ASSET_MODE:" in line]
if primary_mode_lines not in ([], [mode_line]):
    raise SystemExit("unexpected production W4B Compose mode line")
target_without_mode = [line for line in target if "HERMES_UI_ASSET_MODE:" not in line]
primary_without_mode = [line for line in primary if "HERMES_UI_ASSET_MODE:" not in line]
if target_without_mode != primary_without_mode:
    raise SystemExit("target base Compose differs from production baseline beyond W4B mode")
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

INLINE_RETURN_TRAP = "  trap 'rm -f \"$body\" \"$headers\"' RETURN\n"
HASHED_RETURN_TRAP = (
    "  trap 'rm -f \"$body\" \"$headers\" \"$js_headers\" \"$css_headers\" "
    "\"$js_body\" \"$css_body\"' RETURN\n"
)

POSTCHECK_GUARDS = (
    (
        '''  curl --fail --silent --show-error --max-time 8 -D "$headers" "$base/ui" -o "$body" || return 1
''',
        '''  curl --fail --silent --show-error --max-time 8 -D "$headers" "$base/ui" -o "$body" || { printf 'W4B_REASON=postcheck_ui_fetch\\n'; return 1; }
''',
        "hashed W4 UI fetch",
    ),
    (
        '''  grep -Fiq '^X-Hermes-UI-Asset-Mode: hashed-w4' "$headers" || return 1
''',
        '''  grep -Fiq '^X-Hermes-UI-Asset-Mode: hashed-w4' "$headers" || { printf 'W4B_REASON=postcheck_ui_mode_header\\n'; return 1; }
''',
        "hashed W4 mode header",
    ),
    (
        '''  grep -Fiq '^Cache-Control: no-store' "$headers" || return 1
''',
        '''  grep -Fiq '^Cache-Control: no-store' "$headers" || { printf 'W4B_REASON=postcheck_ui_cache_header\\n'; return 1; }
''',
        "hashed W4 UI cache header",
    ),
    (
        '''  grep -Fq '<meta name="hermes-w4-shadow" content="hashed-assets-v1">' "$body" || return 1
''',
        '''  grep -Fq '<meta name="hermes-w4-shadow" content="hashed-assets-v1">' "$body" || { printf 'W4B_REASON=postcheck_ui_marker\\n'; return 1; }
''',
        "hashed W4 marker",
    ),
    (
        '''  ! grep -Fq 'data-hermes-production-bundle=' "$body" || return 1
''',
        '''  ! grep -Fq 'data-hermes-production-bundle=' "$body" || { printf 'W4B_REASON=postcheck_ui_legacy_bundle_marker\\n'; return 1; }
''',
        "hashed W4 legacy bundle marker",
    ),
    (
        '''  ! grep -Fq '/ui/app.js' "$body" || return 1
''',
        '''  ! grep -Fq '/ui/app.js' "$body" || { printf 'W4B_REASON=postcheck_ui_legacy_js_reference\\n'; return 1; }
''',
        "hashed W4 legacy JS reference",
    ),
    (
        '''  ! grep -Fq '/ui/styles.css' "$body" || return 1
''',
        '''  ! grep -Fq '/ui/styles.css' "$body" || { printf 'W4B_REASON=postcheck_ui_legacy_css_reference\\n'; return 1; }
''',
        "hashed W4 legacy CSS reference",
    ),
    (
        '''  [[ -n "$js_path" && -n "$css_path" ]] || return 1
''',
        '''  [[ -n "$js_path" && -n "$css_path" ]] || { printf 'W4B_REASON=postcheck_asset_discovery\\n'; return 1; }
''',
        "hashed W4 asset discovery",
    ),
    (
        '''  [[ "$(printf '%s\\n' "$js_path" | wc -l)" -eq 1 ]] || return 1
''',
        '''  [[ "$(printf '%s\\n' "$js_path" | wc -l)" -eq 1 ]] || { printf 'W4B_REASON=postcheck_js_asset_unique\\n'; return 1; }
''',
        "hashed W4 JS uniqueness",
    ),
    (
        '''  [[ "$(printf '%s\\n' "$css_path" | wc -l)" -eq 1 ]] || return 1
''',
        '''  [[ "$(printf '%s\\n' "$css_path" | wc -l)" -eq 1 ]] || { printf 'W4B_REASON=postcheck_css_asset_unique\\n'; return 1; }
''',
        "hashed W4 CSS uniqueness",
    ),
    (
        '''  curl --fail --silent --show-error --max-time 8 -D "$js_headers" "$base$js_path" -o "$js_body" || return 1
''',
        '''  curl --fail --silent --show-error --max-time 8 -D "$js_headers" "$base$js_path" -o "$js_body" || { printf 'W4B_REASON=postcheck_js_asset_fetch\\n'; return 1; }
''',
        "hashed W4 JS fetch",
    ),
    (
        '''  curl --fail --silent --show-error --max-time 8 -D "$css_headers" "$base$css_path" -o "$css_body" || return 1
''',
        '''  curl --fail --silent --show-error --max-time 8 -D "$css_headers" "$base$css_path" -o "$css_body" || { printf 'W4B_REASON=postcheck_css_asset_fetch\\n'; return 1; }
''',
        "hashed W4 CSS fetch",
    ),
    (
        '''  grep -Fiq '^Content-Type: application/javascript' "$js_headers" || return 1
''',
        '''  grep -Fiq '^Content-Type: application/javascript' "$js_headers" || { printf 'W4B_REASON=postcheck_js_mime\\n'; return 1; }
''',
        "hashed W4 JS MIME",
    ),
    (
        '''  grep -Fiq '^Content-Type: text/css' "$css_headers" || return 1
''',
        '''  grep -Fiq '^Content-Type: text/css' "$css_headers" || { printf 'W4B_REASON=postcheck_css_mime\\n'; return 1; }
''',
        "hashed W4 CSS MIME",
    ),
    (
        '''  grep -Fiq '^Cache-Control: no-store' "$js_headers" || return 1
''',
        '''  grep -Fiq '^Cache-Control: no-store' "$js_headers" || { printf 'W4B_REASON=postcheck_js_cache\\n'; return 1; }
''',
        "hashed W4 JS cache",
    ),
    (
        '''  grep -Fiq '^Cache-Control: no-store' "$css_headers" || return 1
''',
        '''  grep -Fiq '^Cache-Control: no-store' "$css_headers" || { printf 'W4B_REASON=postcheck_css_cache\\n'; return 1; }
''',
        "hashed W4 CSS cache",
    ),
    (
        '''  grep -Fq 'w3-behavior-preserving-bootstrap-v1' "$js_body" || return 1
''',
        '''  grep -Fq 'w3-behavior-preserving-bootstrap-v1' "$js_body" || { printf 'W4B_REASON=postcheck_js_behavior_marker\\n'; return 1; }
''',
        "hashed W4 JS behavior marker",
    ),
    (
        '''  grep -Fq 'HERMES_UI_STYLE_OPEN:' "$css_body" || return 1
''',
        '''  grep -Fq 'HERMES_UI_STYLE_OPEN:' "$css_body" || { printf 'W4B_REASON=postcheck_css_style_marker\\n'; return 1; }
''',
        "hashed W4 CSS style marker",
    ),
    (
        '''  [[ "$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 "$base/ui/assets/not-in-package.js")" == 404 ]] || return 1
''',
        '''  [[ "$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 "$base/ui/assets/not-in-package.js")" == 404 ]] || { printf 'W4B_REASON=postcheck_unknown_asset_404\\n'; return 1; }
''',
        "hashed W4 unknown asset 404",
    ),
    (
        '''  [[ "$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 "$base/ui/assets/w4-shadow-package.json")" == 404 ]] || return 1
''',
        '''  [[ "$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 "$base/ui/assets/w4-shadow-package.json")" == 404 ]] || { printf 'W4B_REASON=postcheck_evidence_asset_404\\n'; return 1; }
''',
        "hashed W4 evidence 404",
    ),
    (
        '''  [[ "$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 8 "$base/ui/review")" == 200 ]] || return 1
''',
        '''  [[ "$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 8 "$base/ui/review")" == 200 ]] || { printf 'W4B_REASON=postcheck_review_200\\n'; return 1; }
''',
        "hashed W4 Review health",
    ),
    (
        '''  curl --fail --silent --show-error --max-time 8 "$base/api/health" | grep -Fq '"status":"ok"' || return 1
''',
        '''  curl --fail --silent --show-error --max-time 8 "$base/api/health" | grep -Fq '"status":"ok"' || { printf 'W4B_REASON=postcheck_api_health\\n'; return 1; }
''',
        "hashed W4 API health",
    ),
    (
        '''  [[ -n "$api" && -n "$web" && -n "$db" ]] || return 1
''',
        '''  [[ -n "$api" && -n "$web" && -n "$db" ]] || { printf 'W4B_REASON=postcheck_target_containers\\n'; return 1; }
''',
        "target runtime containers",
    ),
    (
        '''  [[ "$(docker inspect "$api" --format '{{.Image}}')" == "$(docker image inspect "$TARGET_IMAGE" --format '{{.Id}}')" ]] || return 1
''',
        '''  [[ "$(docker inspect "$api" --format '{{.Image}}')" == "$(docker image inspect "$TARGET_IMAGE" --format '{{.Id}}')" ]] || { printf 'W4B_REASON=postcheck_api_image_identity\\n'; return 1; }
''',
        "target API image identity",
    ),
    (
        '''  [[ "$revision" == "$TARGET_SHA" ]] || return 1
''',
        '''  [[ "$revision" == "$TARGET_SHA" ]] || { printf 'W4B_REASON=postcheck_api_revision\\n'; return 1; }
''',
        "target API revision",
    ),
    (
        '''print(values[0])
')" || return 1
''',
        '''print(values[0])
')" || { printf 'W4B_REASON=postcheck_ui_mode_env_parse\\n'; return 1; }
''',
        "target UI mode parse",
    ),
    (
        '''  [[ "$mode_env" == hashed-w4 ]] || return 1
''',
        '''  [[ "$mode_env" == hashed-w4 ]] || { printf 'W4B_REASON=postcheck_ui_mode_env\\n'; return 1; }
''',
        "target UI mode",
    ),
    (
        '''  web_base="$(resolve_web_base "$web")" || return 1
''',
        '''  web_base="$(resolve_web_base "$web")" || { printf 'W4B_REASON=postcheck_loopback_bind\\n'; return 1; }
''',
        "target loopback bind",
    ),
    (
        '''  nginx_mount="$(resolve_nginx_mount "$web")" || return 1
''',
        '''  nginx_mount="$(resolve_nginx_mount "$web")" || { printf 'W4B_REASON=postcheck_nginx_mount_resolve\\n'; return 1; }
''',
        "target nginx mount resolve",
    ),
    (
        '''  [[ "$(readlink -f -- "$nginx_mount")" == "$(readlink -f -- "$NGINX_TARGET")" ]] || return 1
''',
        '''  [[ "$(readlink -f -- "$nginx_mount")" == "$(readlink -f -- "$NGINX_TARGET")" ]] || { printf 'W4B_REASON=postcheck_nginx_mount_identity\\n'; return 1; }
''',
        "target nginx mount identity",
    ),
)

CUTOVER_POSTCHECK_OLD = '''  if (( APPLY_RC == 0 )) && \\
     [[ "$(service_container db)" == "$DB_BEFORE" ]] && \\
     [[ "$(docker inspect "$(service_container web)" --format '{{.Image}}')" == "$WEB_IMAGE_ID" ]] && \\
     [[ "$(read_live_alembic)" == "$ALEMBIC_BEFORE" ]] && \\
     [[ "$(primary_state)" == "$GIT_BEFORE" ]] && \\
     [[ "$(cloudflared_pid)" == "$CLOUDFLARED_BEFORE" ]] && \\
     assert_target_runtime; then
'''

CUTOVER_POSTCHECK_NEW = '''  if { (( APPLY_RC == 0 )) || { printf 'W4B_REASON=postcheck_compose_apply\\n'; false; }; } && \\
     { [[ "$(service_container db)" == "$DB_BEFORE" ]] || { printf 'W4B_REASON=postcheck_database_container\\n'; false; }; } && \\
     { [[ "$(docker inspect "$(service_container web)" --format '{{.Image}}')" == "$WEB_IMAGE_ID" ]] || { printf 'W4B_REASON=postcheck_web_image_identity\\n'; false; }; } && \\
     { [[ "$(read_live_alembic)" == "$ALEMBIC_BEFORE" ]] || { printf 'W4B_REASON=postcheck_database_revision\\n'; false; }; } && \\
     { [[ "$(primary_state)" == "$GIT_BEFORE" ]] || { printf 'W4B_REASON=postcheck_production_git\\n'; false; }; } && \\
     { [[ "$(cloudflared_pid)" == "$CLOUDFLARED_BEFORE" ]] || { printf 'W4B_REASON=postcheck_cloudflared\\n'; false; }; } && \\
     assert_target_runtime; then
'''

ROLLBACK_REASON_PASS_OLD = "    printf 'W4B_REASON=cutover_validation_failed_auto_rollback_passed\\n'\n"
ROLLBACK_REASON_FAIL_OLD = "  printf 'W4B_REASON=cutover_validation_failed_auto_rollback_failed\\n'\n"
VERIFY_RUNTIME_OLD = "  assert_target_runtime || fail 'hashed_w4_runtime_verification_failed'\n"
VERIFY_RUNTIME_NEW = '''  if ! assert_target_runtime; then
    printf 'W4B_RESULT=BLOCKED\\n'
    printf 'PRODUCTION_MUTATED=false\\n'
    exit 1
  fi
'''

POSTCHECK_TOKENS = (
    "postcheck_ui_fetch",
    "postcheck_ui_mode_header",
    "postcheck_ui_cache_header",
    "postcheck_ui_marker",
    "postcheck_ui_legacy_bundle_marker",
    "postcheck_ui_legacy_js_reference",
    "postcheck_ui_legacy_css_reference",
    "postcheck_asset_discovery",
    "postcheck_js_asset_unique",
    "postcheck_css_asset_unique",
    "postcheck_js_asset_fetch",
    "postcheck_css_asset_fetch",
    "postcheck_js_mime",
    "postcheck_css_mime",
    "postcheck_js_cache",
    "postcheck_css_cache",
    "postcheck_js_behavior_marker",
    "postcheck_css_style_marker",
    "postcheck_unknown_asset_404",
    "postcheck_evidence_asset_404",
    "postcheck_review_200",
    "postcheck_api_health",
    "postcheck_target_containers",
    "postcheck_api_image_identity",
    "postcheck_api_revision",
    "postcheck_ui_mode_env_parse",
    "postcheck_ui_mode_env",
    "postcheck_loopback_bind",
    "postcheck_nginx_mount_resolve",
    "postcheck_nginx_mount_identity",
    "postcheck_compose_apply",
    "postcheck_database_container",
    "postcheck_web_image_identity",
    "postcheck_database_revision",
    "postcheck_production_git",
    "postcheck_cloudflared",
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
        SOURCE_CONTRACT_OLD,
        SOURCE_CONTRACT_NEW,
        "production Compose baseline",
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
    for old, new, label in POSTCHECK_GUARDS:
        rendered = replace_exact_once(rendered, old, new, label)
    rendered = replace_exact_once(
        rendered,
        CUTOVER_POSTCHECK_OLD,
        CUTOVER_POSTCHECK_NEW,
        "cutover postcheck diagnostics",
    )
    rendered = replace_exact_once(
        rendered,
        ROLLBACK_REASON_PASS_OLD,
        "",
        "successful auto-rollback generic reason",
    )
    rendered = replace_exact_once(
        rendered,
        ROLLBACK_REASON_FAIL_OLD,
        "",
        "failed auto-rollback generic reason",
    )
    rendered = replace_exact_once(
        rendered,
        VERIFY_RUNTIME_OLD,
        VERIFY_RUNTIME_NEW,
        "verify runtime diagnostic preservation",
    )

    if BASELINE_OLD in rendered or ROLLBACK_OLD in rendered:
        raise SystemExit("stale W4B image validator remains after rendering")
    if COMMANDS_OLD in rendered or GIT_STATE_OLD in rendered:
        raise SystemExit("stale W4B production Git state path remains after rendering")
    if SOURCE_CONTRACT_OLD in rendered:
        raise SystemExit("stale W4B production Compose baseline remains after rendering")
    if COMPOSE_STDIN_HEAD_OLD in rendered or COMPOSE_STDIN_TAIL_OLD in rendered:
        raise SystemExit("stale W4B Compose validator stdin path remains after rendering")
    if COMPOSE_STDIN_HEAD_NEW not in rendered:
        raise SystemExit("Compose validator python -c marker mismatch")
    if rendered.count("current_api_main_tag_revision_mismatch") != 1:
        raise SystemExit("managed-main revision binding marker mismatch")
    if rendered.count('hermes-deals-api:main-([0-9a-f]{12})') != 2:
        raise SystemExit("managed-main tag validation marker mismatch")
    if rendered.count('runuser -u andris -- git -C "$PRIMARY" "$@"') != 1:
        raise SystemExit("production Git owner-identity marker mismatch")
    if rendered.count("unexpected production W4B Compose mode line") != 1:
        raise SystemExit("production Compose mode validation marker mismatch")
    if rendered.count("primary_without_mode") != 2:
        raise SystemExit("production Compose normalization marker mismatch")
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
    for token in POSTCHECK_TOKENS:
        if rendered.count(f"W4B_REASON={token}") != 1:
            raise SystemExit(f"postcheck diagnostic marker mismatch: {token}")
    if "cutover_validation_failed_auto_rollback_passed" in rendered:
        raise SystemExit("generic successful auto-rollback reason must not mask failed check")
    if "cutover_validation_failed_auto_rollback_failed" in rendered:
        raise SystemExit("generic failed auto-rollback reason must not mask failed check")
    if "hashed_w4_runtime_verification_failed" in rendered:
        raise SystemExit("generic verify reason must not mask failed check")
    if "safe.directory" in rendered:
        raise SystemExit("safe.directory bypass is forbidden")

    output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
