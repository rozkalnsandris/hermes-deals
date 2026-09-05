from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / "tools/runner/release/hermes-deals-release-dispatch"


def test_issue19_dispatcher_accepts_only_bounded_managed_baselines() -> None:
    subprocess.run(["bash", "-n", str(DISPATCHER)], check=True)
    text = DISPATCHER.read_text(encoding="utf-8")

    assert '^hermes-deals-api:(main|w4b|w4c)-([0-9a-f]{12})$' in text
    assert '^hermes-deals-api:release-[A-Za-z0-9_.-]+$' in text
    assert 'MANAGED_BASELINE_SHA="${BASH_REMATCH[2]}"' in text
    assert '[[ "$MANAGED_BASELINE_SHA" == "${CURRENT_IMAGE_REVISION:0:12}" ]]' in text
    assert "managed production baseline requires an exact OCI revision label" in text
    assert "managed production baseline tag does not match OCI revision" in text
    assert "production image is not a managed Hermes Deals release image" in text
    assert '[[ "$CURRENT_IMAGE_TAG" == hermes-deals-api:release-* ]]' not in text

    # Keep the existing exact rollback identity and fail-closed legacy fallback.
    assert '[[ "$CURRENT_IMAGE_ID" == "$ROLLBACK_IMAGE_ID" ]]' in text
    assert '[[ "$CURRENT_IMAGE_REVISION" == "$ROLLBACK_SHA" ]]' in text
    assert '[[ "$CURRENT_IMAGE_TAG" == "$ROLLBACK_TAG" ]]' in text
    assert "production OCI revision does not match registered rollback baseline" in text
