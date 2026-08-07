from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools" / "lidl_parser_provenance"))
TOOL = ROOT / "tools" / "lidl_gate_b_family_scan.py"
SPEC = importlib.util.spec_from_file_location("lidl_gate_b_family_scan_tested", TOOL)
assert SPEC and SPEC.loader
scan_tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scan_tool
SPEC.loader.exec_module(scan_tool)


@dataclass(frozen=True)
class FakeFlyer:
    discovered_at: object


class FakeShadow:
    def analyze_lidl_pdf(self, *, document, flyer, snapshot_id, collected_at):
        assert document == b"synthetic-pdf"
        assert flyer.discovered_at == collected_at
        return {
            "parser_version": scan_tool.PARSER_VERSION,
            "base_parser_version": "base-test",
            "base_metrics": {"rows": 2},
            "v6_metrics": {"rows": 2},
            "shadow_rows": [
                {
                    "page": 1,
                    "product_name": "A",
                    "channel": "physical_store",
                    "scope": "in_scope",
                    "production_ready_shadow": True,
                    "warnings": [],
                },
                {
                    "page": 2,
                    "product_name": "B",
                    "channel": "physical_store",
                    "scope": "review",
                    "production_ready_shadow": False,
                    "warnings": ["review"],
                },
            ],
        }


def _family(tmp_path: Path) -> Path:
    family = tmp_path / "aktionsprospekt-03-08-2026-08-08-2026-test"
    family.mkdir(parents=True)
    (family / "source.pdf").write_bytes(b"synthetic-pdf")
    (family / "source.json").write_text(
        json.dumps(
            {
                "dateTime": "2026-08-07T09:10:11+02:00",
                "flyer": {
                    "id": "synthetic-flyer",
                    "flyerUrlAbsolute": "https://example.invalid/viewer",
                    "hiResPdfUrl": "https://example.invalid/source.pdf",
                    "offerStartDate": "2026-08-03",
                    "offerEndDate": "2026-08-08",
                    "regions": [{"code": "21"}],
                    "pages": [{}, {}],
                    "products": {},
                },
            },
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    return family


def test_independent_clean_builds_are_byte_deterministic(tmp_path: Path, monkeypatch) -> None:
    family = _family(tmp_path)
    monkeypatch.setattr(scan_tool, "load_lidl_v631", lambda: SimpleNamespace(shadow=FakeShadow()))
    monkeypatch.setattr(
        scan_tool.staging,
        "_make_flyer",
        lambda meta, source_json: FakeFlyer(discovered_at=None),
    )

    first = scan_tool.build_scan(
        frozen_family=family,
        output_root=tmp_path / "out-a",
        route_region="21",
    )
    second = scan_tool.build_scan(
        frozen_family=family,
        output_root=tmp_path / "out-b",
        route_region="21",
    )
    assert first["result"] == second["result"] == "STAGED_SCAN_READY"
    assert first["scan"].startswith("scan-v631-")
    assert first["observed_at"] == second["observed_at"] == "2026-08-07T07:10:11+00:00"
    assert first["scan_tree_sha256"] == second["scan_tree_sha256"]

    first_scan = tmp_path / "out-a" / "flyers" / family.name / "scans" / first["scan"]
    second_scan = tmp_path / "out-b" / "flyers" / family.name / "scans" / second["scan"]
    first_files = sorted(path.relative_to(first_scan) for path in first_scan.rglob("*") if path.is_file())
    second_files = sorted(path.relative_to(second_scan) for path in second_scan.rglob("*") if path.is_file())
    assert first_files == second_files
    for relative in first_files:
        assert (first_scan / relative).read_bytes() == (second_scan / relative).read_bytes()


def test_existing_identical_scan_is_noop(tmp_path: Path, monkeypatch) -> None:
    family = _family(tmp_path)
    monkeypatch.setattr(scan_tool, "load_lidl_v631", lambda: SimpleNamespace(shadow=FakeShadow()))
    monkeypatch.setattr(
        scan_tool.staging,
        "_make_flyer",
        lambda meta, source_json: FakeFlyer(discovered_at=None),
    )
    first = scan_tool.build_scan(
        frozen_family=family,
        output_root=tmp_path / "out",
        route_region="21",
    )
    replay = scan_tool.build_scan(
        frozen_family=family,
        output_root=tmp_path / "out",
        route_region="21",
    )
    assert first["result"] == "STAGED_SCAN_READY"
    assert replay["result"] == "NO_OP_IDENTICAL"
    assert replay["staging_write"] is False
    assert replay["scan_tree_sha256"] == first["scan_tree_sha256"]
