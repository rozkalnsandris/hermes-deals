#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import sys
from typing import NoReturn

FIELD_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
TOKEN = FIELD_NAME


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def final_fields(path: Path) -> dict[str, list[str]]:
    if not path.is_file() or path.is_symlink():
        fail("header file is missing or unsafe")
    try:
        text = path.read_bytes().decode("iso-8859-1")
    except OSError as exc:
        fail(f"header file read failed: {exc}")

    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("HTTP/"):
            if current is not None:
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
    if current is not None:
        blocks.append(current)
    if not blocks:
        fail("no HTTP response header block")

    fields: dict[str, list[str]] = {}
    for line in blocks[-1]:
        if line[:1] in {" ", "\t"}:
            fail("obsolete folded header is forbidden")
        name, sep, value = line.partition(":")
        if not sep or FIELD_NAME.fullmatch(name) is None:
            fail("malformed HTTP field")
        fields.setdefault(name.casefold(), []).append(value.strip(" \t"))
    return fields


def split_http_list(value: str) -> list[str]:
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
        fail("malformed quoted HTTP list")
    items.append(value[start:])
    return items


def cache_directives(fields: dict[str, list[str]]) -> list[tuple[str, str | None]]:
    values = fields.get("cache-control", [])
    if not values:
        fail("Cache-Control field missing")
    directives: list[tuple[str, str | None]] = []
    for value in values:
        for raw in split_http_list(value):
            item = raw.strip(" \t")
            if not item:
                fail("empty Cache-Control directive")
            name, sep, raw_value = item.partition("=")
            name = name.strip(" \t").casefold()
            if TOKEN.fullmatch(name) is None:
                fail("invalid Cache-Control directive name")
            parameter: str | None = None
            if sep:
                parameter = raw_value.strip(" \t")
                if not parameter:
                    fail("empty Cache-Control directive value")
            directives.append((name, parameter))
    return directives


def require_exact_cache(fields: dict[str, list[str]], expected: dict[str, str | None]) -> None:
    directives = cache_directives(fields)
    if len(directives) != len(expected):
        fail("Cache-Control directive count mismatch")
    actual: dict[str, str | None] = {}
    for name, value in directives:
        if name in actual:
            fail("duplicate Cache-Control directive")
        actual[name] = value
    if actual != expected:
        fail("Cache-Control semantics mismatch")


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: http_header_contract.py <header-file> <check>")
    path = Path(sys.argv[1])
    check = sys.argv[2]
    fields = final_fields(path)

    if check == "mode-hashed-w4":
        if fields.get("x-hermes-ui-asset-mode") != ["hashed-w4"]:
            fail("W4 mode header mismatch")
    elif check == "mime-js":
        values = fields.get("content-type", [])
        if (
            len(values) != 1
            or values[0].split(";", 1)[0].strip().casefold()
            != "application/javascript"
        ):
            fail("JavaScript MIME mismatch")
    elif check == "mime-css":
        values = fields.get("content-type", [])
        if (
            len(values) != 1
            or values[0].split(";", 1)[0].strip().casefold() != "text/css"
        ):
            fail("CSS MIME mismatch")
    elif check == "cache-w4b":
        require_exact_cache(fields, {"no-store": None})
    elif check == "cache-html-w4c":
        require_exact_cache(fields, {"no-cache": None})
    elif check == "cache-asset-w4c":
        require_exact_cache(
            fields,
            {"public": None, "max-age": "31536000", "immutable": None},
        )
    else:
        fail("unknown header contract check")


if __name__ == "__main__":
    main()
