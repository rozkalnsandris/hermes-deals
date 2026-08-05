from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / "tools/runner/release/hermes-deals-release-register"


def test_docker_label_templates_are_valid_for_posix_shell() -> None:
    subprocess.run(["bash", "-n", str(REGISTER)], check=True)
    text = REGISTER.read_text(encoding="utf-8")

    correct = "'{{index .Config.Labels \"org.opencontainers.image.revision\"}}'"
    escaped_inside_single_quotes = (
        "'{{index .Config.Labels \\\"org.opencontainers.image.revision\\\"}}'"
    )

    assert text.count(correct) == 2
    assert escaped_inside_single_quotes not in text
