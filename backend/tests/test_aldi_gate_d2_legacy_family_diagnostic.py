from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"

spec = importlib.util.spec_from_file_location(
    "aldi_gate_d2_legacy_family_diagnostic",
    TOOLS / "aldi_gate_d2_legacy_family_diagnostic.py",
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

GATE_D = TOOLS / "aldi_weekly_gate_d_visual_review_pack.py"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_family(root: Path, *, drop: tuple[str, int] | None = None, current_count: int = 49) -> Path:
    run = root / "a30-v02-runs" / "20260805T103228Z"
    page_root = run / "raw" / "page-images"
    rows = []
    for label, count in (("current", current_count), ("preview", 41)):
        for page in range(1, count + 1):
            data = b"\xff\xd8" + f"{label}-{page}".encode() + (b"x" * 10_050)
            source = page_root / label / f"page-{page:03d}.img"
            if drop != (label, page):
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(data)
            rows.append(
                {
                    "label": label,
                    "page_number": page,
                    "sha256": _sha(data),
                    "bytes": len(data),
                    "format": "jpeg",
                }
            )
    manifest = run / "reports" / "page-image-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    return manifest


def test_complete_49_plus_41_family_is_found(tmp_path: Path) -> None:
    manifest = _build_family(tmp_path)
    result = module.diagnose(state_root=tmp_path, gate_d_tool=GATE_D)
    assert result["decision"] == module.FOUND
    assert result["candidate_count"] == 1
    assert result["valid_candidate_count"] == 1
    row = result["candidates"][0]
    assert row["manifest_path"] == manifest.relative_to(tmp_path).as_posix()
    assert row["current_rows"] == 49
    assert row["preview_rows"] == 41
    assert row["valid"] is True
    assert row["failure_stage"] is None
    assert result["safety"]["strict_49_plus_41_frozen_contract_unchanged"] is True
    assert result["production_eligible"] is False


def test_missing_image_is_structured_not_raw_exception(tmp_path: Path) -> None:
    _build_family(tmp_path, drop=("current", 7))
    result = module.diagnose(state_root=tmp_path, gate_d_tool=GATE_D)
    assert result["decision"] == module.NONE
    row = result["candidates"][0]
    assert row["manifest_contract_valid"] is True
    assert row["failure_stage"] == "image_validation"
    assert row["missing_images"] == 1
    assert "error" not in row
    assert result["raw_exception_exported"] is False
    assert result["raw_evidence_exported"] is False


def test_wrong_page_count_reports_manifest_contract_stage(tmp_path: Path) -> None:
    _build_family(tmp_path, current_count=48)
    result = module.diagnose(state_root=tmp_path, gate_d_tool=GATE_D)
    assert result["decision"] == module.NONE
    row = result["candidates"][0]
    assert row["current_rows"] == 48
    assert row["preview_rows"] == 41
    assert row["total_rows"] == 89
    assert row["manifest_contract_valid"] is False
    assert row["failure_stage"] == "manifest_contract"


def test_no_manifest_candidates_is_explicit(tmp_path: Path) -> None:
    result = module.diagnose(state_root=tmp_path, gate_d_tool=GATE_D)
    assert result["decision"] == module.NONE
    assert result["candidate_count"] == 0
    assert result["valid_candidate_count"] == 0
    assert result["failure_stage_counts"] == {}
    assert result["next_step"] == "prepare_immutable_legacy_family_recovery"
