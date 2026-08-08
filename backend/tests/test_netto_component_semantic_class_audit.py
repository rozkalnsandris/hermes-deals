from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


TOOL = Path(__file__).resolve().parents[2] / "tools" / "netto_component_semantic_class_audit.py"
SPEC = importlib.util.spec_from_file_location("netto_component_semantic_class_audit", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _component(*, price_groups=1, anchors=1, text=1, images=1):
    node_count = price_groups + anchors + text + images
    complete = price_groups > 0 and anchors > 0 and text > 0
    return {
        "component_id": "ignored-by-semantic-class",
        "node_count": node_count,
        "node_type_counts": {
            "price_group": price_groups,
            "price_anchor": anchors,
            "text_block": text,
            "image": images,
        },
        "complete_commercial_component": complete,
        "full_commercial_component": complete and images > 0,
        "nonprice_fragment_component": price_groups == 0,
        "image_text_nonprice_component": price_groups == 0 and images > 0 and text > 0,
        "orphan_price_component": price_groups > 0 and (anchors == 0 or text == 0),
        "multi_price_group_component": price_groups >= 2,
        "normalized_bbox": {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0},
    }


def _row(cell_id: str, ownership: str, components):
    return {
        "cell_id": cell_id,
        "page_number": 1,
        "component_signature": {},
        "components": list(components),
        "independent_ownership": ownership,
    }


def _payload():
    rows = []
    normal = [_component()]
    fragmented = [_component(), _component(price_groups=0, anchors=0, text=1, images=1)]
    for index in range(88):
        rows.append(_row(f"s{index:03d}", "single_source", normal if index < 80 else fragmented))
    for index in range(10):
        rows.append(_row(f"m{index:03d}", "mixed_source", fragmented if index < 6 else normal))
    for index in range(2):
        rows.append(_row(f"e{index:03d}", "excluded_control", [_component(price_groups=0, anchors=0, text=1, images=0)]))
    return {
        "schema_version": 1,
        "strategy": "netto_object_component_signature_audit_v1",
        "source_cell_count": 100,
        "frozen_signature_sha256": "a" * 64,
        "rows": rows,
        "classification_performed": False,
        "parser_behavior_changed": False,
        "review_only": True,
        "promotion_ready": False,
        "image_binary_retained": False,
        "ocr_used": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "deployment_performed": False,
    }


class NettoComponentSemanticClassAuditTest(unittest.TestCase):
    def test_freeze_rejects_truth_bearing_row(self):
        with self.assertRaises(MODULE.NettoComponentSemanticClassAuditError):
            MODULE.freeze_semantic_class(
                _row("x", "mixed_source", [_component()])
            )

    def test_semantic_class_ignores_geometry_and_component_identity(self):
        first = _row("x", "single_source", [_component()])
        second = _row("x", "single_source", [_component()])
        second["components"][0]["component_id"] = "different"
        second["components"][0]["normalized_bbox"] = {
            "x0": 0.2,
            "y0": 0.1,
            "x1": 0.8,
            "y1": 0.9,
        }
        first.pop("independent_ownership")
        second.pop("independent_ownership")
        self.assertEqual(
            MODULE.freeze_semantic_class(first)["semantic_class_sha256"],
            MODULE.freeze_semantic_class(second)["semantic_class_sha256"],
        )

    def test_truth_swap_does_not_change_frozen_semantic_classes(self):
        payload = _payload()
        frozen_before = MODULE.freeze_semantic_classes(payload)
        before_sha = MODULE._sha256(frozen_before)
        payload["rows"][0]["independent_ownership"] = "mixed_source"
        payload["rows"][88]["independent_ownership"] = "single_source"
        frozen_after = MODULE.freeze_semantic_classes(payload)
        self.assertEqual(before_sha, MODULE._sha256(frozen_after))

    def test_replay_reports_shared_mixed_classes_without_promotion(self):
        result = MODULE.replay_semantic_class_audit(_payload())
        self.assertEqual(result["semantic_class_count"], 3)
        self.assertEqual(result["mixed_source_class_count"], 2)
        self.assertEqual(result["mixed_only_non_excluded_class_count"], 0)
        self.assertEqual(result["mixed_source_cells_in_mixed_only_classes"], 0)
        self.assertEqual(result["single_source_cells_sharing_mixed_classes"], 88)
        self.assertFalse(result["classification_performed"])
        self.assertFalse(result["parser_behavior_changed"])
        self.assertTrue(result["review_only"])
        self.assertFalse(result["promotion_ready"])

    def test_replay_fails_closed_on_unsafe_source_flag(self):
        payload = _payload()
        payload["parser_behavior_changed"] = True
        with self.assertRaises(MODULE.NettoComponentSemanticClassAuditError):
            MODULE.replay_semantic_class_audit(payload)


if __name__ == "__main__":
    unittest.main()
