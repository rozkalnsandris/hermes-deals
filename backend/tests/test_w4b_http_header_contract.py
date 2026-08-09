from __future__ import annotations

from pathlib import Path
import shlex
import subprocess


ROOT = Path(__file__).resolve().parents[2]
OPERATOR = ROOT / "tools" / "runner" / "w4b" / "hermes-deals-w4b-operator"
RENDERER = ROOT / "tools" / "runner" / "w4b" / "render-hermes-deals-w4b-operator.py"

OLD_PREDICATES = (
    "grep -Fiq '^X-Hermes-UI-Asset-Mode: hashed-w4'",
    "grep -Fiq '^Cache-Control: no-store' \"$headers\"",
    "grep -Fiq '^Content-Type: application/javascript'",
    "grep -Fiq '^Content-Type: text/css'",
    "grep -Fiq '^Cache-Control: no-store' \"$js_headers\"",
    "grep -Fiq '^Cache-Control: no-store' \"$css_headers\"",
)


def render_operator(tmp_path: Path, template: Path = OPERATOR) -> str:
    output = tmp_path / "rendered-operator"
    subprocess.run(
        ["python3", str(RENDERER), str(template), str(output)],
        check=True,
    )
    subprocess.run(["bash", "-n", str(output)], check=True)
    return output.read_text(encoding="utf-8")


def extract_helper(source: str) -> str:
    start = source.index("http_header_matches() {\n")
    end = source.index("\nassert_inline_w3() (\n", start)
    return source[start:end] + "\n"


def run_helper(tmp_path: Path, header_bytes: bytes, mode: str, name: str, expected: str) -> int:
    source = render_operator(tmp_path)
    helper = extract_helper(source)
    headers = tmp_path / "headers.txt"
    headers.write_bytes(header_bytes)
    arguments = " ".join(shlex.quote(value) for value in (str(headers), mode, name, expected))
    script = helper + f"\nhttp_header_matches {arguments}\n"
    return subprocess.run(["bash", "-c", script], check=False).returncode


def test_rendered_operator_removes_all_literal_caret_fixed_header_checks(tmp_path: Path) -> None:
    source = render_operator(tmp_path)

    for predicate in OLD_PREDICATES:
        assert predicate not in source
    assert source.count("http_header_matches() {") == 1
    assert source.count('http_header_matches "$headers" singleton') == 1
    assert source.count('http_header_matches "$headers" cache-directive') == 1
    assert source.count('http_header_matches "$js_headers" media-type') == 1
    assert source.count('http_header_matches "$css_headers" media-type') == 1
    assert source.count('http_header_matches "$js_headers" cache-directive') == 1
    assert source.count('http_header_matches "$css_headers" cache-directive') == 1


def test_singleton_header_accepts_crlf_ows_and_case_insensitive_field_name(tmp_path: Path) -> None:
    headers = (
        b"HTTP/1.1 200 OK\r\n"
        b"x-HeRmEs-Ui-AsSeT-MoDe:\t hashed-w4 \t\r\n"
        b"Cache-Control: no-store\r\n\r\n"
    )
    assert run_helper(tmp_path, headers, "singleton", "X-Hermes-UI-Asset-Mode", "hashed-w4") == 0


def test_singleton_header_rejects_duplicate_or_wrong_mode(tmp_path: Path) -> None:
    duplicate = (
        b"HTTP/1.1 200 OK\r\n"
        b"X-Hermes-UI-Asset-Mode: hashed-w4\r\n"
        b"x-hermes-ui-asset-mode: hashed-w4\r\n\r\n"
    )
    wrong = b"HTTP/1.1 200 OK\r\nX-Hermes-UI-Asset-Mode: inline-w3\r\n\r\n"
    assert run_helper(tmp_path, duplicate, "singleton", "X-Hermes-UI-Asset-Mode", "hashed-w4") != 0
    assert run_helper(tmp_path, wrong, "singleton", "X-Hermes-UI-Asset-Mode", "hashed-w4") != 0


def test_media_type_is_case_insensitive_and_allows_parameters(tmp_path: Path) -> None:
    valid = b"HTTP/1.1 200 OK\r\ncOnTeNt-TyPe: Application/JavaScript; charset=UTF-8\r\n\r\n"
    invalid = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
    assert run_helper(tmp_path, valid, "media-type", "Content-Type", "application/javascript") == 0
    assert run_helper(tmp_path, invalid, "media-type", "Content-Type", "application/javascript") != 0


def test_cache_control_requires_case_insensitive_no_store_directive(tmp_path: Path) -> None:
    valid = (
        b"HTTP/1.1 200 OK\r\n"
        b"Cache-Control: private, max-age=0\r\n"
        b"cache-control: No-StOrE\r\n\r\n"
    )
    quoted_comma = (
        b"HTTP/1.1 200 OK\r\n"
        b"Cache-Control: private=\"a,b\", no-store\r\n\r\n"
    )
    invalid = b"HTTP/1.1 200 OK\r\nCache-Control: private, max-age=0\r\n\r\n"
    assert run_helper(tmp_path, valid, "cache-directive", "Cache-Control", "no-store") == 0
    assert run_helper(tmp_path, quoted_comma, "cache-directive", "Cache-Control", "no-store") == 0
    assert run_helper(tmp_path, invalid, "cache-directive", "Cache-Control", "no-store") != 0


def test_parser_uses_final_curl_header_block(tmp_path: Path) -> None:
    headers = (
        b"HTTP/1.1 100 Continue\r\nX-Hermes-UI-Asset-Mode: inline-w3\r\n\r\n"
        b"HTTP/1.1 200 OK\r\nX-Hermes-UI-Asset-Mode: hashed-w4\r\n\r\n"
    )
    assert run_helper(tmp_path, headers, "singleton", "X-Hermes-UI-Asset-Mode", "hashed-w4") == 0


def test_header_parser_template_drift_fails_closed(tmp_path: Path) -> None:
    drifted = tmp_path / "drifted-operator"
    drifted.write_text(
        OPERATOR.read_text(encoding="utf-8").replace(
            "grep -Fiq '^X-Hermes-UI-Asset-Mode: hashed-w4'",
            "grep -Fiq 'X-Hermes-UI-Asset-Mode: hashed-w4'",
            1,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output"
    result = subprocess.run(
        ["python3", str(RENDERER), str(drifted), str(output)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "hashed W4 mode header replacement expected exactly once" in (
        result.stdout + result.stderr
    )
    assert not output.exists()
