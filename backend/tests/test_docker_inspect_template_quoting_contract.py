from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / "tools/runner/release/hermes-deals-release-register"
DISPATCHER = ROOT / "tools/runner/release/hermes-deals-release-dispatch"


def test_docker_label_templates_are_valid_for_posix_shell() -> None:
    correct = "'{{index .Config.Labels \"org.opencontainers.image.revision\"}}'"
    escaped_inside_single_quotes = (
        "'{{index .Config.Labels \\\"org.opencontainers.image.revision\\\"}}'"
    )

    for path, expected_count in ((REGISTER, 2), (DISPATCHER, 2)):
        subprocess.run(["bash", "-n", str(path)], check=True)
        text = path.read_text(encoding="utf-8")
        assert text.count(correct) == expected_count
        assert escaped_inside_single_quotes not in text


def test_dispatcher_label_inspection_failures_are_explicit() -> None:
    text = DISPATCHER.read_text(encoding="utf-8")

    for marker in (
        "registered new image ID could not be inspected",
        "registered new image revision label could not be inspected",
        "registered rollback image ID could not be inspected",
        "production API image ID could not be inspected",
        "production API image tag could not be inspected",
        "production API revision label could not be inspected",
    ):
        assert marker in text
