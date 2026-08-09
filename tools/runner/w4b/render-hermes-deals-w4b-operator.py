#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile


BASE_RENDERER = Path(__file__).with_name("render-hermes-deals-w4b-operator.base.py")

HTTP_HEADER_HELPER = r'''http_header_matches() {
  local header_file="$1"
  local mode="$2"
  local expected_name="$3"
  local expected_value="$4"
  python3 - "$header_file" "$mode" "$expected_name" "$expected_value" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
mode = sys.argv[2]
expected_name = sys.argv[3]
expected_value = sys.argv[4]
if not path.is_file() or path.is_symlink():
    raise SystemExit(2)

text = path.read_bytes().decode("iso-8859-1")
blocks: list[list[str]] = []
current: list[str] | None = None
for line in text.splitlines():
    if line.startswith("HTTP/"):
        if current:
            blocks.append(current)
        current = []
        continue
    if current is None:
        continue
    if line == "":
        blocks.append(current)
        current = None
        continue
    current.append(line)
if current:
    blocks.append(current)
if not blocks:
    raise SystemExit(2)

field_name = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
fields: dict[str, list[str]] = {}
for line in blocks[-1]:
    if line[:1] in (" ", "\t"):
        raise SystemExit(2)
    name, sep, value = line.partition(":")
    if not sep or not field_name.fullmatch(name):
        raise SystemExit(2)
    fields.setdefault(name.casefold(), []).append(value.strip(" \t"))

values = fields.get(expected_name.casefold(), [])
if mode == "singleton":
    if values != [expected_value]:
        raise SystemExit(2)
elif mode == "media-type":
    if len(values) != 1:
        raise SystemExit(2)
    media_type = values[0].split(";", 1)[0].strip(" \t").casefold()
    if media_type != expected_value.casefold():
        raise SystemExit(2)
elif mode == "cache-directive":
    if not values:
        raise SystemExit(2)

    def split_list(value: str) -> list[str]:
        items: list[str] = []
        start = 0
        quoted = False
        escaped = False
        for index, char in enumerate(value):
            if escaped:
                escaped = False
                continue
            if quoted and char == "\\":
                escaped = True
                continue
            if char == '"':
                quoted = not quoted
                continue
            if char == "," and not quoted:
                items.append(value[start:index])
                start = index + 1
        if quoted or escaped:
            raise SystemExit(2)
        items.append(value[start:])
        return items

    directives: list[str] = []
    for value in values:
        for raw_item in split_list(value):
            item = raw_item.strip(" \t")
            if not item:
                raise SystemExit(2)
            name = item.split("=", 1)[0].strip(" \t")
            if not field_name.fullmatch(name):
                raise SystemExit(2)
            directives.append(name.casefold())
    if expected_value.casefold() not in directives:
        raise SystemExit(2)
else:
    raise SystemExit(2)
PY
}

'''

HEADER_REPLACEMENTS = (
    (
        r'''  grep -Fiq '^X-Hermes-UI-Asset-Mode: hashed-w4' "$headers" || { printf 'W4B_REASON=postcheck_ui_mode_header\n'; return 1; }
''',
        r'''  http_header_matches "$headers" singleton 'X-Hermes-UI-Asset-Mode' 'hashed-w4' || { printf 'W4B_REASON=postcheck_ui_mode_header\n'; return 1; }
''',
        "UI mode header",
    ),
    (
        r'''  grep -Fiq '^Cache-Control: no-store' "$headers" || { printf 'W4B_REASON=postcheck_ui_cache_header\n'; return 1; }
''',
        r'''  http_header_matches "$headers" cache-directive 'Cache-Control' 'no-store' || { printf 'W4B_REASON=postcheck_ui_cache_header\n'; return 1; }
''',
        "UI cache header",
    ),
    (
        r'''  grep -Fiq '^Content-Type: application/javascript' "$js_headers" || { printf 'W4B_REASON=postcheck_js_mime\n'; return 1; }
''',
        r'''  http_header_matches "$js_headers" media-type 'Content-Type' 'application/javascript' || { printf 'W4B_REASON=postcheck_js_mime\n'; return 1; }
''',
        "JS media type",
    ),
    (
        r'''  grep -Fiq '^Content-Type: text/css' "$css_headers" || { printf 'W4B_REASON=postcheck_css_mime\n'; return 1; }
''',
        r'''  http_header_matches "$css_headers" media-type 'Content-Type' 'text/css' || { printf 'W4B_REASON=postcheck_css_mime\n'; return 1; }
''',
        "CSS media type",
    ),
    (
        r'''  grep -Fiq '^Cache-Control: no-store' "$js_headers" || { printf 'W4B_REASON=postcheck_js_cache\n'; return 1; }
''',
        r'''  http_header_matches "$js_headers" cache-directive 'Cache-Control' 'no-store' || { printf 'W4B_REASON=postcheck_js_cache\n'; return 1; }
''',
        "JS cache header",
    ),
    (
        r'''  grep -Fiq '^Cache-Control: no-store' "$css_headers" || { printf 'W4B_REASON=postcheck_css_cache\n'; return 1; }
''',
        r'''  http_header_matches "$css_headers" cache-directive 'Cache-Control' 'no-store' || { printf 'W4B_REASON=postcheck_css_cache\n'; return 1; }
''',
        "CSS cache header",
    ),
)

STALE_HEADER_PREDICATES = tuple(old.strip() for old, _, _ in HEADER_REPLACEMENTS)


def replace_exact_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label} replacement expected exactly once, found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: render-hermes-deals-w4b-operator.py <template> <output>")
    if not BASE_RENDERER.is_file() or BASE_RENDERER.is_symlink():
        raise SystemExit("base W4B renderer is missing or unsafe")

    template = Path(sys.argv[1])
    output = Path(sys.argv[2])
    if not template.is_file() or template.is_symlink():
        raise SystemExit("operator template is missing or unsafe")

    with tempfile.TemporaryDirectory(prefix="hermes-w4b-render-") as directory:
        base_output = Path(directory) / "operator"
        subprocess.run(
            [sys.executable, str(BASE_RENDERER), str(template), str(base_output)],
            check=True,
        )
        rendered = base_output.read_text(encoding="utf-8")

    anchor = "assert_inline_w3() (\n"
    if rendered.count(anchor) != 1:
        raise SystemExit("HTTP helper insertion anchor mismatch")
    rendered = rendered.replace(anchor, HTTP_HEADER_HELPER + anchor, 1)

    for old, new, label in HEADER_REPLACEMENTS:
        rendered = replace_exact_once(rendered, old, new, label)

    for predicate in STALE_HEADER_PREDICATES:
        if predicate in rendered:
            raise SystemExit("stale fixed-string HTTP header predicate remains")
    if rendered.count("http_header_matches() {\n") != 1:
        raise SystemExit("HTTP header helper marker mismatch")
    if rendered.count("http_header_matches \"$headers\" singleton") != 1:
        raise SystemExit("W4 mode header helper call mismatch")
    if rendered.count("http_header_matches \"$headers\" cache-directive") != 1:
        raise SystemExit("UI cache helper call mismatch")
    if rendered.count("http_header_matches \"$js_headers\" media-type") != 1:
        raise SystemExit("JS media-type helper call mismatch")
    if rendered.count("http_header_matches \"$css_headers\" media-type") != 1:
        raise SystemExit("CSS media-type helper call mismatch")
    if rendered.count("http_header_matches \"$js_headers\" cache-directive") != 1:
        raise SystemExit("JS cache helper call mismatch")
    if rendered.count("http_header_matches \"$css_headers\" cache-directive") != 1:
        raise SystemExit("CSS cache helper call mismatch")

    output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
