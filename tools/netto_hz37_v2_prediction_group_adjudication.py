#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
from typing import Any, Mapping
import zipfile

from netto_heldout_ownership_protocol import ACCEPTANCE, PROTOCOL_NAME as BASE_PROTOCOL_NAME
from netto_heldout_ownership_protocol_v2 import PROTOCOL_NAME as V2_PROTOCOL_NAME, prepare_v2_freeze
from netto_heldout_prediction_group_adjudication import OUTCOME_CLASSES, HeldoutAdjudicationError, adjudicate_group

STRATEGY = "netto_hz37_v2_prediction_group_adjudication_v1"
EXPECTED_CAMPAIGN = "hz37_hasb"
EXPECTED_STORE = "5659"
EXPECTED_SCOPE = "family_primary_netto"
EXPECTED_VALID_FROM = "2026-09-07"
EXPECTED_VALID_UNTIL = "2026-09-12"
EXPECTED_SOURCE_SHA256 = "7b5b04bcf4af5c51f6ddfbd40096595e8a6da9cd7dd701c2d11b2916e0cd7951"
EXPECTED_PDF_SHA256 = "7da859b19345891538521d2ec3b0be75fb9b2a2675626a6dbd942f15f1356322"
EXPECTED_BASE_FREEZE_SHA256 = "4f8381892d3b4e3847267c34c27a3b52131331b42c660ecb812cb5756f79617a"
EXPECTED_V2_FREEZE_SHA256 = "77da6e4ed772d3a513df8dafa6d20c6882ca7ad3da729ac3d76d0ece7b7d4922"
EXPECTED_ARTIFACT_ID = 10022687292
EXPECTED_RUN_ID = 34132489970
EXPECTED_ARTIFACT_NAME = "netto-heldout-v2-fbe3cfa143788607446d0095ae1f887354d10eb3-run-34132489970"
EXPECTED_ARTIFACT_ZIP_SHA256 = "6a6394e91df0aab2681f7c042397cc4c572f4254e3f7df008840165f97cae2dc"
EXPECTED_ARTIFACT_BYTES = 41514323
EXPECTED_REGISTERED_COMMIT = "fbe3cfa143788607446d0095ae1f887354d10eb3"
EXPECTED_CANDIDATE_IMPLEMENTATION_COMMIT = "17ceedf0fdb0342acb594ed20679519ec4910e3c"
EXPECTED_CANDIDATE_FILE_SHA256 = "60c57d7474464b66349cc9761eb4d4dd7895a470bf7634f1d091f73bf00718b6"
EXPECTED_CANDIDATE_PROVENANCE_SHA256 = "adb4581a45423e5cb093fb49037a8e9a1448ecc13940318d5ee455cff825ee9f"
EXPECTED_CANDIDATE_DECISIONS_SHA256 = "ed406f6cb0e5f1a3ed2e6355aba9dd90fa2f9d59aaee99192307c5448e34225a"
EXPECTED_TRUTH_SHA256 = "ee859fc903012a8c617caa63446ad889a4b4f237c324b9e6a43f2a792b43d52c"
EXPECTED_PAGES = 73
REQUIRED_MEMBERS = frozenset({
    "capture/predictions.json",
    "capture/freeze-manifest.json",
    "capture/freeze-receipt.json",
    "capture/candidate-provenance.json",
    "capture/freeze-manifest-v2.json",
    "capture/freeze-receipt-v2.json",
})


class Hz37V2AdjudicationError(HeldoutAdjudicationError):
    pass


def _file_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise Hz37V2AdjudicationError(f"input must be a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _load_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Hz37V2AdjudicationError(f"invalid JSON: {label}") from exc
    if not isinstance(payload, dict):
        raise Hz37V2AdjudicationError(f"JSON root must be an object: {label}")
    return payload


def _load_json_file(path: Path) -> dict[str, Any]:
    _file_sha256(path)
    return _load_json_bytes(path.read_bytes(), str(path))


def _validate_archive_member(info: zipfile.ZipInfo) -> None:
    pure = PurePosixPath(info.filename)
    mode = (info.external_attr >> 16) & 0xFFFF
    if (
        info.is_dir()
        or info.filename.startswith("/")
        or "\\" in info.filename
        or any(part in {"", ".", ".."} for part in pure.parts)
        or stat.S_ISLNK(mode)
        or stat.S_ISCHR(mode)
        or stat.S_ISBLK(mode)
        or stat.S_ISFIFO(mode)
        or stat.S_ISSOCK(mode)
    ):
        raise Hz37V2AdjudicationError(f"unsafe artifact member: {info.filename}")


def _read_artifact(artifact_zip: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    if artifact_zip.is_symlink() or not artifact_zip.is_file():
        raise Hz37V2AdjudicationError("held-out artifact ZIP must be a regular non-symlink file")
    if artifact_zip.stat().st_size != EXPECTED_ARTIFACT_BYTES:
        raise Hz37V2AdjudicationError("held-out artifact byte-size mismatch")
    if _file_sha256(artifact_zip) != EXPECTED_ARTIFACT_ZIP_SHA256:
        raise Hz37V2AdjudicationError("held-out artifact ZIP SHA mismatch")
    with zipfile.ZipFile(artifact_zip) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(set(names)) != len(names):
            raise Hz37V2AdjudicationError("duplicate held-out artifact member name")
        for info in infos:
            _validate_archive_member(info)
        if not REQUIRED_MEMBERS.issubset(set(names)):
            missing = sorted(REQUIRED_MEMBERS - set(names))
            raise Hz37V2AdjudicationError(f"required held-out members missing: {missing}")
        raw = {name: archive.read(name) for name in REQUIRED_MEMBERS}
    payloads = {name: _load_json_bytes(value, name) for name, value in raw.items()}
    digests = {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}
    return payloads, digests


def _validate_receipts(retention_path: Path, truth_receipt_path: Path) -> None:
    retention = _load_json_file(retention_path)
    actions = retention.get("actions_artifact")
    independent = retention.get("independent_copy")
    expected_retention = {
        "schema": "hermes.netto.heldout-independent-retention.v1",
        "campaign_key": EXPECTED_CAMPAIGN,
        "base_freeze_manifest_sha256": EXPECTED_BASE_FREEZE_SHA256,
        "v2_freeze_manifest_sha256": EXPECTED_V2_FREEZE_SHA256,
        "candidate_implementation_commit": EXPECTED_CANDIDATE_IMPLEMENTATION_COMMIT,
        "candidate_file_sha256": EXPECTED_CANDIDATE_FILE_SHA256,
        "candidate_provenance_sha256": EXPECTED_CANDIDATE_PROVENANCE_SHA256,
        "candidate_decisions_sha256": EXPECTED_CANDIDATE_DECISIONS_SHA256,
        "registered_commit": EXPECTED_REGISTERED_COMMIT,
        "independent_copy_verified": True,
        "candidate_payload_opened": False,
    }
    for key, expected in expected_retention.items():
        if retention.get(key) != expected:
            raise Hz37V2AdjudicationError(f"retention receipt mismatch: {key}")
    if not isinstance(actions, Mapping) or not isinstance(independent, Mapping):
        raise Hz37V2AdjudicationError("retention receipt artifact binding missing")
    if (
        actions.get("id") != EXPECTED_ARTIFACT_ID
        or actions.get("workflow_run_id") != EXPECTED_RUN_ID
        or actions.get("name") != EXPECTED_ARTIFACT_NAME
        or actions.get("size_bytes") != EXPECTED_ARTIFACT_BYTES
        or actions.get("zip_sha256") != EXPECTED_ARTIFACT_ZIP_SHA256
    ):
        raise Hz37V2AdjudicationError("retention Actions artifact binding mismatch")
    if independent.get("zip_sha256") != EXPECTED_ARTIFACT_ZIP_SHA256 or independent.get("size_bytes") != EXPECTED_ARTIFACT_BYTES:
        raise Hz37V2AdjudicationError("independent retained-copy binding mismatch")

    receipt = _load_json_file(truth_receipt_path)
    expected_truth_receipt = {
        "strategy": "netto_hz37_completed_source_truth_receipt_v1",
        "campaign_key": EXPECTED_CAMPAIGN,
        "completed_source_truth_sha256": EXPECTED_TRUTH_SHA256,
        "freeze_manifest_sha256": EXPECTED_BASE_FREEZE_SHA256,
        "page_count": EXPECTED_PAGES,
        "frozen_predictions_opened": False,
        "candidate_provenance_opened": False,
        "adjudication_started": False,
        "review_only": True,
        "promotion_ready": False,
    }
    for key, expected in expected_truth_receipt.items():
        if receipt.get(key) != expected:
            raise Hz37V2AdjudicationError(f"truth receipt mismatch: {key}")


def _validate_truth(truth_path: Path) -> dict[str, Any]:
    if _file_sha256(truth_path) != EXPECTED_TRUTH_SHA256:
        raise Hz37V2AdjudicationError("completed source truth SHA mismatch")
    truth = _load_json_bytes(truth_path.read_bytes(), str(truth_path))
    expected = {
        "strategy": "netto_hz37_independent_source_truth_v1",
        "campaign_key": EXPECTED_CAMPAIGN,
        "campaign_window": {"start": EXPECTED_VALID_FROM, "end": EXPECTED_VALID_UNTIL},
        "store_external_id": EXPECTED_STORE,
        "scope": EXPECTED_SCOPE,
        "source_sha256": EXPECTED_SOURCE_SHA256,
        "source_pdf_sha256": EXPECTED_PDF_SHA256,
        "freeze_manifest_sha256": EXPECTED_BASE_FREEZE_SHA256,
        "page_count": EXPECTED_PAGES,
        "truth_unit": "independent_source_region",
        "frozen_predictions_opened": False,
        "candidate_provenance_opened": False,
        "adjudication_started": False,
    }
    for key, value in expected.items():
        if truth.get(key) != value:
            raise Hz37V2AdjudicationError(f"completed truth contract mismatch: {key}")
    pages = truth.get("pages")
    if not isinstance(pages, list) or len(pages) != EXPECTED_PAGES:
        raise Hz37V2AdjudicationError("completed truth page coverage mismatch")
    return truth


def _validate_frozen_candidate(
    members: Mapping[str, Mapping[str, Any]], member_digests: Mapping[str, str]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    base_manifest = dict(members["capture/freeze-manifest.json"])
    base_receipt = dict(members["capture/freeze-receipt.json"])
    candidate = dict(members["capture/candidate-provenance.json"])
    if member_digests["capture/candidate-provenance.json"] != EXPECTED_CANDIDATE_FILE_SHA256:
        raise Hz37V2AdjudicationError("candidate provenance file SHA mismatch")
    rebuilt_manifest, rebuilt_receipt = prepare_v2_freeze(
        base_manifest,
        base_receipt,
        candidate,
        candidate_file_sha256=EXPECTED_CANDIDATE_FILE_SHA256,
        candidate_implementation_commit=EXPECTED_CANDIDATE_IMPLEMENTATION_COMMIT,
    )
    if rebuilt_manifest != members["capture/freeze-manifest-v2.json"]:
        raise Hz37V2AdjudicationError("v2 freeze manifest reconstruction mismatch")
    if rebuilt_receipt != members["capture/freeze-receipt-v2.json"]:
        raise Hz37V2AdjudicationError("v2 freeze receipt reconstruction mismatch")
    expected_receipt = {
        "v2_freeze_manifest_sha256": EXPECTED_V2_FREEZE_SHA256,
        "base_freeze_manifest_sha256": EXPECTED_BASE_FREEZE_SHA256,
        "candidate_implementation_commit": EXPECTED_CANDIDATE_IMPLEMENTATION_COMMIT,
        "candidate_file_sha256": EXPECTED_CANDIDATE_FILE_SHA256,
        "candidate_provenance_sha256": EXPECTED_CANDIDATE_PROVENANCE_SHA256,
        "candidate_decisions_sha256": EXPECTED_CANDIDATE_DECISIONS_SHA256,
        "truth_available_at_freeze": False,
        "review_only": True,
        "promotion_ready": False,
    }
    for key, expected in expected_receipt.items():
        if rebuilt_receipt.get(key) != expected:
            raise Hz37V2AdjudicationError(f"frozen v2 receipt mismatch: {key}")
    if base_receipt.get("freeze_manifest_sha256") != EXPECTED_BASE_FREEZE_SHA256:
        raise Hz37V2AdjudicationError("base freeze identity mismatch")
    return base_manifest, candidate, rebuilt_receipt


def _validate_predictions(
    predictions: Mapping[str, Any], base_manifest: Mapping[str, Any], predictions_file_sha256: str
) -> None:
    expected = {
        "schema_version": 1,
        "protocol": BASE_PROTOCOL_NAME,
        "strategy": "netto_heldout_all_pages_predictions_v1",
        "store_external_id": EXPECTED_STORE,
        "scope": EXPECTED_SCOPE,
        "campaign_key": EXPECTED_CAMPAIGN,
        "campaign_window": {"start": EXPECTED_VALID_FROM, "end": EXPECTED_VALID_UNTIL},
        "source_identity_sha256": EXPECTED_SOURCE_SHA256,
        "source_pdf_sha256": EXPECTED_PDF_SHA256,
        "prediction_parser_identity": base_manifest.get("parser_identity"),
        "page_count": EXPECTED_PAGES,
        "capture_scope": "all_pdf_pages",
        "review_only": True,
        "promotion_ready": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "database_write_performed": False,
        "deployment_performed": False,
        "truth_included": False,
        "expected_metadata_included": False,
        "review_labels_included": False,
    }
    for key, value in expected.items():
        if predictions.get(key) != value:
            raise Hz37V2AdjudicationError(f"frozen prediction contract mismatch: {key}")
    if base_manifest.get("predictions_sha256") != predictions_file_sha256:
        raise Hz37V2AdjudicationError("frozen predictions SHA mismatch")


def _metric(status: str, observed: Any, threshold: Any, reason: str | None = None) -> dict[str, Any]:
    row = {"status": status, "observed": observed, "threshold": threshold}
    if reason:
        row["reason"] = reason
    return row


def build_metrics(
    rows: list[dict[str, Any]], *, automatic_candidate_parent_reuse_count: int
) -> tuple[dict[str, Any], bool]:
    counts = Counter(row["outcome"] for row in rows)
    resolved = sum(counts[name] for name in OUTCOME_CLASSES)
    automatic = [row for row in rows if row["candidate_auto_single"] is True]
    mixed_auto = sum(row["outcome"] == "mixed_source" for row in automatic)
    excluded_auto = sum(row["outcome"] == "excluded_control" for row in automatic)
    auto_single_correct = sum(row["outcome"] == "single_source" for row in automatic)
    auto_precision = auto_single_correct / len(automatic) if automatic else None
    metrics = {
        "minimum_reviewed_cells": _metric(
            "PASS" if resolved >= ACCEPTANCE["minimum_reviewed_cells"] else "FAIL",
            resolved,
            ACCEPTANCE["minimum_reviewed_cells"],
            "Legacy protocol term 'cells' is reported using resolved frozen prediction groups.",
        ),
        "minimum_mixed_source_cells": _metric(
            "PASS" if counts["mixed_source"] >= ACCEPTANCE["minimum_mixed_source_cells"] else "FAIL",
            counts["mixed_source"],
            ACCEPTANCE["minimum_mixed_source_cells"],
            "Legacy protocol term 'cells' is reported using frozen prediction groups.",
        ),
        "maximum_mixed_source_auto_single": _metric(
            "PASS" if mixed_auto <= ACCEPTANCE["maximum_mixed_source_auto_single"] else "FAIL",
            mixed_auto,
            ACCEPTANCE["maximum_mixed_source_auto_single"],
        ),
        "maximum_excluded_control_auto_eligible": _metric(
            "PASS" if excluded_auto <= ACCEPTANCE["maximum_excluded_control_auto_eligible"] else "FAIL",
            excluded_auto,
            ACCEPTANCE["maximum_excluded_control_auto_eligible"],
        ),
        "minimum_auto_single_precision": (
            _metric(
                "PASS" if auto_precision >= ACCEPTANCE["minimum_auto_single_precision"] else "FAIL",
                auto_precision,
                ACCEPTANCE["minimum_auto_single_precision"],
            )
            if auto_precision is not None
            else _metric(
                "NOT_EVALUABLE",
                None,
                ACCEPTANCE["minimum_auto_single_precision"],
                "The frozen hz37 v2 candidate contains zero candidate_auto_single decisions.",
            )
        ),
        "maximum_cross_cell_group_reuse": _metric(
            "PASS" if automatic_candidate_parent_reuse_count <= ACCEPTANCE["maximum_cross_cell_group_reuse"] else "FAIL",
            automatic_candidate_parent_reuse_count,
            ACCEPTANCE["maximum_cross_cell_group_reuse"],
            "Measured from the frozen v2 candidate exclusive-parent contract.",
        ),
    }
    return metrics, all(row["status"] == "PASS" for row in metrics.values())


def adjudicate(
    artifact_zip: Path,
    truth_path: Path,
    retention_path: Path,
    truth_receipt_path: Path,
) -> dict[str, Any]:
    _validate_receipts(retention_path, truth_receipt_path)
    truth = _validate_truth(truth_path)
    members, member_digests = _read_artifact(artifact_zip)
    base_manifest, candidate, v2_receipt = _validate_frozen_candidate(members, member_digests)
    predictions = dict(members["capture/predictions.json"])
    _validate_predictions(predictions, base_manifest, member_digests["capture/predictions.json"])
    if candidate.get("predictions_sha256") != base_manifest.get("predictions_sha256"):
        raise Hz37V2AdjudicationError("candidate/prediction freeze identity mismatch")
    if candidate.get("page_count") != EXPECTED_PAGES:
        raise Hz37V2AdjudicationError("candidate page coverage mismatch")

    truth_pages = {int(page["page_number"]): page for page in truth["pages"]}
    candidate_pages_raw = candidate.get("pages")
    prediction_pages = predictions.get("pages")
    if not isinstance(candidate_pages_raw, list):
        raise Hz37V2AdjudicationError("candidate page list missing")
    candidate_pages = {int(page["page_number"]): page for page in candidate_pages_raw}
    expected_pages = set(range(1, EXPECTED_PAGES + 1))
    if (
        set(truth_pages) != expected_pages
        or set(candidate_pages) != expected_pages
        or not isinstance(prediction_pages, list)
        or len(prediction_pages) != EXPECTED_PAGES
    ):
        raise Hz37V2AdjudicationError("truth/candidate/prediction page coverage mismatch")

    rows: list[dict[str, Any]] = []
    seen_units: set[str] = set()
    for page_number, prediction_page in enumerate(prediction_pages, start=1):
        if not isinstance(prediction_page, Mapping) or prediction_page.get("page_number") != page_number:
            raise Hz37V2AdjudicationError("prediction pages must be sequential")
        analysis = prediction_page.get("analysis")
        if not isinstance(analysis, Mapping):
            raise Hz37V2AdjudicationError("prediction analysis missing")
        truth_page = truth_pages[page_number]
        candidate_page = candidate_pages[page_number]
        page_meta = analysis.get("page")
        if not isinstance(page_meta, Mapping):
            raise Hz37V2AdjudicationError("prediction page metadata missing")
        for predicted_key, truth_key in (("width_points", "page_width_points"), ("height_points", "page_height_points")):
            if abs(float(page_meta.get(predicted_key) or 0.0) - float(truth_page[truth_key])) > 0.001:
                raise Hz37V2AdjudicationError("prediction/truth page dimensions mismatch")
        if (
            abs(float(candidate_page.get("page_width_points") or 0.0) - float(truth_page["page_width_points"])) > 0.001
            or abs(float(candidate_page.get("page_height_points") or 0.0) - float(truth_page["page_height_points"])) > 0.001
        ):
            raise Hz37V2AdjudicationError("candidate/truth page dimensions mismatch")

        spans_raw = analysis.get("spans")
        anchors_raw = analysis.get("price_anchors")
        groups = analysis.get("groups")
        if not isinstance(spans_raw, list) or not isinstance(anchors_raw, list) or not isinstance(groups, list):
            raise Hz37V2AdjudicationError("prediction page arrays invalid")
        spans = {int(span["index"]): span for span in spans_raw}
        anchors = {str(anchor["anchor_id"]): anchor for anchor in anchors_raw}
        if len(spans) != len(spans_raw) or len(anchors) != len(anchors_raw):
            raise Hz37V2AdjudicationError("duplicate prediction atom identity")

        candidate_groups = candidate_page.get("groups")
        if not isinstance(candidate_groups, list):
            raise Hz37V2AdjudicationError("candidate page groups missing")
        candidate_by_unit = {
            str(group.get("prediction_unit_id") or ""): group
            for group in candidate_groups
            if isinstance(group, Mapping)
        }
        if len(candidate_by_unit) != len(candidate_groups) or "" in candidate_by_unit:
            raise Hz37V2AdjudicationError("candidate prediction unit identity invalid")

        page_units: set[str] = set()
        for group in groups:
            if not isinstance(group, Mapping):
                raise Hz37V2AdjudicationError("prediction group must be object")
            row = adjudicate_group(
                page_number=page_number,
                group=group,
                spans=spans,
                anchors=anchors,
                source_regions=truth_page["source_regions"],
            )
            unit = row["prediction_unit_id"]
            frozen_candidate = candidate_by_unit.get(unit)
            if frozen_candidate is None:
                raise Hz37V2AdjudicationError("candidate missing frozen prediction unit")
            mapped_atom_ids = [atom["atom_id"] for atom in row["atoms"]]
            if mapped_atom_ids != frozen_candidate.get("atom_ids"):
                raise Hz37V2AdjudicationError("candidate/prediction atom ownership mismatch")
            if unit in seen_units:
                raise Hz37V2AdjudicationError("duplicate prediction unit")
            seen_units.add(unit)
            page_units.add(unit)
            row["candidate_auto_single"] = frozen_candidate.get("candidate_auto_single") is True
            row["candidate_primary_parent_unit_id"] = frozen_candidate.get("primary_parent_unit_id")
            row["candidate_parent_unit_ids"] = frozen_candidate.get("parent_unit_ids")
            row["candidate_reasons"] = frozen_candidate.get("candidate_reasons")
            row.pop("frozen_production_eligible", None)
            row.pop("frozen_route", None)
            rows.append(row)
        if page_units != set(candidate_by_unit):
            raise Hz37V2AdjudicationError("candidate contains prediction units absent from frozen predictions")

    counts = Counter(row["outcome"] for row in rows)
    metrics, acceptance_all_pass = build_metrics(
        rows,
        automatic_candidate_parent_reuse_count=int(v2_receipt["automatic_candidate_parent_reuse_count"]),
    )
    return {
        "schema_version": 1,
        "strategy": STRATEGY,
        "protocol": V2_PROTOCOL_NAME,
        "campaign_key": EXPECTED_CAMPAIGN,
        "campaign_window": {"start": EXPECTED_VALID_FROM, "end": EXPECTED_VALID_UNTIL},
        "store_external_id": EXPECTED_STORE,
        "scope": EXPECTED_SCOPE,
        "source_sha256": EXPECTED_SOURCE_SHA256,
        "source_pdf_sha256": EXPECTED_PDF_SHA256,
        "artifact_id": EXPECTED_ARTIFACT_ID,
        "artifact_workflow_run_id": EXPECTED_RUN_ID,
        "artifact_zip_sha256": EXPECTED_ARTIFACT_ZIP_SHA256,
        "registered_commit": EXPECTED_REGISTERED_COMMIT,
        "candidate_implementation_commit": EXPECTED_CANDIDATE_IMPLEMENTATION_COMMIT,
        "base_freeze_manifest_sha256": EXPECTED_BASE_FREEZE_SHA256,
        "v2_freeze_manifest_sha256": EXPECTED_V2_FREEZE_SHA256,
        "predictions_sha256": base_manifest["predictions_sha256"],
        "candidate_file_sha256": EXPECTED_CANDIDATE_FILE_SHA256,
        "candidate_provenance_sha256": EXPECTED_CANDIDATE_PROVENANCE_SHA256,
        "candidate_decisions_sha256": EXPECTED_CANDIDATE_DECISIONS_SHA256,
        "completed_source_truth_sha256": EXPECTED_TRUTH_SHA256,
        "mapping_strategy": "frozen_candidate_group_owned_atom_center_to_independent_source_region_v1",
        "coordinate_space": "unrotated_page_points",
        "prediction_unit": "frozen_geometry_group",
        "protocol_legacy_unit_term": "cell",
        "page_count": EXPECTED_PAGES,
        "prediction_group_count": len(rows),
        "candidate_auto_single_count": sum(row["candidate_auto_single"] for row in rows),
        "resolved_prediction_group_count": sum(counts[name] for name in OUTCOME_CLASSES),
        "outcome_counts": dict(sorted(counts.items())),
        "acceptance": dict(ACCEPTANCE),
        "metrics": metrics,
        "required_metric_not_evaluable_count": sum(row["status"] == "NOT_EVALUABLE" for row in metrics.values()),
        "acceptance_all_pass": acceptance_all_pass,
        "review_only": True,
        "promotion_ready": False,
        "parser_behavior_changed": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "deployment_performed": False,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Adjudicate frozen Netto hz37 v2 candidate decisions against frozen independent source truth.")
    parser.add_argument("--artifact-zip", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--retention-receipt", type=Path, required=True)
    parser.add_argument("--truth-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise Hz37V2AdjudicationError("adjudication output must be create-only")
    payload = adjudicate(args.artifact_zip, args.truth, args.retention_receipt, args.truth_receipt)
    encoded = _json_bytes(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    summary = {
        "adjudication_sha256": hashlib.sha256(encoded).hexdigest(),
        "prediction_group_count": payload["prediction_group_count"],
        "candidate_auto_single_count": payload["candidate_auto_single_count"],
        "resolved_prediction_group_count": payload["resolved_prediction_group_count"],
        "outcome_counts": payload["outcome_counts"],
        "required_metric_not_evaluable_count": payload["required_metric_not_evaluable_count"],
        "acceptance_all_pass": payload["acceptance_all_pass"],
        "promotion_ready": payload["promotion_ready"],
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
