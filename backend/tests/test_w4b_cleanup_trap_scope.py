from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
OPERATOR = ROOT / "tools" / "runner" / "w4b" / "hermes-deals-w4b-operator"
RENDERER = ROOT / "tools" / "runner" / "w4b" / "render-hermes-deals-w4b-operator.py"


def render_operator(tmp_path: Path) -> str:
    output = tmp_path / "hermes-deals-w4b-operator"
    subprocess.run(
        ["python3", str(RENDERER), str(OPERATOR), str(output)],
        check=True,
    )
    subprocess.run(["bash", "-n", str(output)], check=True)
    return output.read_text(encoding="utf-8")


def test_w4b_ui_assertion_cleanup_is_subshell_scoped(tmp_path: Path) -> None:
    source = render_operator(tmp_path)

    assert "assert_inline_w3() (\n" in source
    assert "assert_hashed_w4() (\n" in source
    assert "assert_target_runtime() {\n" in source

    assert "trap 'rm -f \"$body\" \"$headers\"' EXIT" in source
    assert (
        "trap 'rm -f \"$body\" \"$headers\" \"$js_headers\" \"$css_headers\" "
        "\"$js_body\" \"$css_body\"' EXIT"
    ) in source

    assert "trap 'rm -f \"$body\" \"$headers\"' RETURN" not in source
    assert (
        "trap 'rm -f \"$body\" \"$headers\" \"$js_headers\" \"$css_headers\" "
        "\"$js_body\" \"$css_body\"' RETURN"
    ) not in source


def test_subshell_exit_cleanup_survives_outer_function_return_under_nounset() -> None:
    probe = r'''
set -Eeuo pipefail
assert_probe() (
  local body headers
  body="$(mktemp)"
  headers="$(mktemp)"
  trap 'rm -f "$body" "$headers"' EXIT
  test -f "$body"
  test -f "$headers"
)
outer() {
  assert_probe
  printf 'outer-return-pass\n'
}
outer
'''
    result = subprocess.run(
        ["bash", "-c", probe],
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout == "outer-return-pass\n"
