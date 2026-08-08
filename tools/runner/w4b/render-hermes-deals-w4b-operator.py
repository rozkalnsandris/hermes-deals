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


def replace_exact_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label} replacement expected exactly once, found {count}")
    return source.replace(old, new, 1)


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

    if BASELINE_OLD in rendered or ROLLBACK_OLD in rendered:
        raise SystemExit("stale W4B image validator remains after rendering")
    if rendered.count("current_api_main_tag_revision_mismatch") != 1:
        raise SystemExit("managed-main revision binding marker mismatch")
    if rendered.count('hermes-deals-api:main-([0-9a-f]{12})') != 2:
        raise SystemExit("managed-main tag validation marker mismatch")

    output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
