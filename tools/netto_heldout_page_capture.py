from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Mapping, Sequence

import pymupdf


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import netto_visual_geometry_shadow as geometry  # noqa: E402
from netto_heldout_ownership_protocol import (  # noqa: E402
    EXISTING_EVALUATION_CAMPAIGNS,
    OWNERSHIP_CLASSES,
    PROTOCOL_NAME,
    prepare_freeze,
    source_campaign_key,
)
from netto_shadow_promotion import (  # noqa: E402
    EvidenceBinding,
    EvidenceStatus,
    verify_binding_files,
)


EVIDENCE_STRATEGY = "netto_heldout_all_pages_source_evidence_v1"
PREDICTION_STRATEGY = "netto_heldout_all_pages_predictions_v1"
REVIEW_TEMPLATE_STRATEGY = "netto_heldout_blind_source_review_v1"
ARTIFACT_FILES = (
    "source-evidence.json",
    "predictions.json",
    "freeze-manifest.json",
    "freeze-receipt.json",
    "blind-review-template.json",
)


class HeldoutCaptureError(ValueError):
    pass


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _canonical_digest(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    if path.exists() or path.is_symlink():
        raise HeldoutCaptureError(f"create-only output already exists: {path.name}")
    path.write_bytes(_json_bytes(payload))


def _rounded_values(value: Any, size: int) -> list[float] | None:
    try:
        values = [round(float(item), 3) for item in value]
    except (TypeError, ValueError):
        return None
    return values if len(values) == size else None


def _image_metadata(page: pymupdf.Page) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in page.get_image_info(hashes=True, xrefs=True):
        bbox = _rounded_values(raw.get("bbox"), 4)
        transform = _rounded_values(raw.get("transform"), 6)
        digest = raw.get("digest")
        digest_hex = bytes(digest).hex() if isinstance(digest, (bytes, bytearray)) else None
        rows.append(
            {
                "bbox": bbox,
                "transform": transform,
                "width": int(raw.get("width") or 0),
                "height": int(raw.get("height") or 0),
                "bpc": int(raw.get("bpc") or 0),
                "colorspace": int(raw.get("colorspace") or 0),
                "xref": int(raw.get("xref") or 0),
                "digest_hex": digest_hex,
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            row["bbox"] or [],
            row["xref"],
            row["digest_hex"] or "",
            row["width"],
            row["height"],
        ),
    )


def _validate_binding(binding_payload: Mapping[str, Any]) -> tuple[EvidenceBinding, str, Path]:
    binding = EvidenceBinding.from_mapping(binding_payload)
    binding.validate()
    if binding.evidence_status is not EvidenceStatus.PDF_BOUND:
        raise HeldoutCaptureError("held-out page capture requires pdf_bound evidence")
    verification = verify_binding_files(binding)
    if verification.status is not EvidenceStatus.PDF_BOUND:
        raise HeldoutCaptureError(f"held-out source binding is not verified: {verification.reason}")
    campaign_key = source_campaign_key(binding)
    if campaign_key in EXISTING_EVALUATION_CAMPAIGNS:
        raise HeldoutCaptureError("held-out campaign overlaps the existing evaluation corpus")
    if not binding.pdf_path or not binding.pdf_sha256:
        raise HeldoutCaptureError("verified PDF path/SHA are required")
    pdf_path = Path(binding.pdf_path)
    if pdf_path.is_symlink() or not pdf_path.is_file():
        raise HeldoutCaptureError("verified PDF must remain a regular non-symlink file")
    return binding, campaign_key, pdf_path


def _capture_payloads(
    binding: EvidenceBinding,
    campaign_key: str,
    pdf_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_identity = binding.identity_sha256()
    evidence_pages: list[dict[str, Any]] = []
    prediction_pages: list[dict[str, Any]] = []

    try:
        document = pymupdf.open(pdf_path)
    except Exception as exc:  # PyMuPDF has several format/open exception classes.
        raise HeldoutCaptureError(f"cannot open verified held-out PDF: {exc}") from exc
    try:
        page_count = int(document.page_count)
        if page_count <= 0:
            raise HeldoutCaptureError("held-out PDF must contain at least one page")
        image_rows = {
            page_number: _image_metadata(document.load_page(page_number - 1))
            for page_number in range(1, page_count + 1)
        }
    finally:
        document.close()

    for page_number in range(1, page_count + 1):
        try:
            layout = geometry.extract_layout_from_pdf(pdf_path, page_number)
            analysis = geometry.analyze_layout(layout)
        except Exception as exc:
            raise HeldoutCaptureError(f"page {page_number} source/prediction capture failed: {exc}") from exc
        layout_page = layout.get("page") if isinstance(layout, Mapping) else None
        analysis_page = analysis.get("page") if isinstance(analysis, Mapping) else None
        if not isinstance(layout_page, Mapping) or not isinstance(analysis_page, Mapping):
            raise HeldoutCaptureError(f"page {page_number} metadata is missing")
        if int(layout_page.get("page_number") or 0) != page_number:
            raise HeldoutCaptureError(f"page {page_number} layout identity mismatch")
        if int(analysis_page.get("page_number") or 0) != page_number:
            raise HeldoutCaptureError(f"page {page_number} prediction identity mismatch")
        if analysis.get("parser_identity") != geometry.PARSER_IDENTITY:
            raise HeldoutCaptureError("prediction parser identity drift")
        layout_sha256 = _canonical_digest(layout)
        evidence_pages.append(
            {
                "page_number": page_number,
                "layout_sha256": layout_sha256,
                "layout": layout,
                "images": image_rows[page_number],
            }
        )
        prediction_pages.append(
            {
                "page_number": page_number,
                "layout_sha256": layout_sha256,
                "analysis": analysis,
            }
        )

    common = {
        "schema_version": 1,
        "protocol": PROTOCOL_NAME,
        "store_external_id": binding.store_external_id,
        "scope": binding.scope,
        "campaign_key": campaign_key,
        "campaign_window": {
            "start": binding.valid_from.isoformat(),
            "end": binding.valid_until.isoformat(),
        },
        "source_identity_sha256": source_identity,
        "source_manifest_sha256": binding.manifest_sha256,
        "source_html_sha256": binding.html_sha256,
        "source_pdf_sha256": binding.pdf_sha256,
        "source_parser_identity": binding.parser_identity,
        "prediction_parser_identity": geometry.PARSER_IDENTITY,
        "page_count": page_count,
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
    evidence = {
        **common,
        "strategy": EVIDENCE_STRATEGY,
        "pymupdf_version": str(getattr(pymupdf, "pymupdf_version", "unknown")),
        "pages": evidence_pages,
    }
    predictions = {
        **common,
        "strategy": PREDICTION_STRATEGY,
        "pages": prediction_pages,
    }
    return evidence, predictions


def _blind_review_template(
    freeze_manifest: Mapping[str, Any],
    freeze_receipt: Mapping[str, Any],
    page_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "strategy": REVIEW_TEMPLATE_STRATEGY,
        "protocol": PROTOCOL_NAME,
        "campaign_key": freeze_manifest["campaign_key"],
        "campaign_window": freeze_manifest["campaign_window"],
        "store_external_id": freeze_manifest["store_external_id"],
        "source_sha256": freeze_manifest["source_sha256"],
        "evidence_sha256": freeze_manifest["evidence_sha256"],
        "predictions_sha256": freeze_manifest["predictions_sha256"],
        "freeze_manifest_sha256": freeze_receipt["freeze_manifest_sha256"],
        "prediction_parser_identity": freeze_manifest["parser_identity"],
        "ownership_classes": list(OWNERSHIP_CLASSES),
        "page_count": page_count,
        "review_status": "blank_before_independent_review",
        "truth_available_at_freeze": False,
        "parser_predictions_included": False,
        "expected_truth_included": False,
        "review_only": True,
        "promotion_ready": False,
        "pages": [
            {"page_number": page_number, "source_cards": []}
            for page_number in range(1, page_count + 1)
        ],
    }


def _write_sha256s(root: Path, names: Sequence[str]) -> None:
    lines = [f"{_file_sha256(root / name)}  {name}" for name in sorted(names)]
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def capture_heldout(binding_payload: Mapping[str, Any], output: Path) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise HeldoutCaptureError("held-out output directory must not already exist")
    binding, campaign_key, pdf_path = _validate_binding(binding_payload)
    evidence, predictions = _capture_payloads(binding, campaign_key, pdf_path)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(mode=0o700)
    completed = False
    try:
        evidence_path = output / "source-evidence.json"
        predictions_path = output / "predictions.json"
        _write_json(evidence_path, evidence)
        _write_json(predictions_path, predictions)

        freeze_manifest, freeze_receipt = prepare_freeze(
            dict(binding_payload),
            geometry.PARSER_IDENTITY,
            evidence_path,
            predictions_path,
        )
        if freeze_manifest["campaign_key"] != campaign_key:
            raise HeldoutCaptureError("source campaign identity changed during capture")
        if freeze_manifest["source_sha256"] != binding.identity_sha256():
            raise HeldoutCaptureError("source evidence identity changed during capture")

        _write_json(output / "freeze-manifest.json", freeze_manifest)
        _write_json(output / "freeze-receipt.json", freeze_receipt)
        review_template = _blind_review_template(
            freeze_manifest,
            freeze_receipt,
            int(evidence["page_count"]),
        )
        _write_json(output / "blind-review-template.json", review_template)
        _write_sha256s(output, ARTIFACT_FILES)
        completed = True
        return {
            "campaign_key": campaign_key,
            "source_sha256": freeze_manifest["source_sha256"],
            "evidence_sha256": freeze_manifest["evidence_sha256"],
            "predictions_sha256": freeze_manifest["predictions_sha256"],
            "freeze_manifest_sha256": freeze_receipt["freeze_manifest_sha256"],
            "prediction_parser_identity": geometry.PARSER_IDENTITY,
            "page_count": evidence["page_count"],
            "truth_available_at_freeze": False,
            "review_only": True,
            "promotion_ready": False,
        }
    finally:
        if not completed and output.exists():
            shutil.rmtree(output)


def _load_binding(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise HeldoutCaptureError("binding input must be a regular non-symlink file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HeldoutCaptureError("binding input must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise HeldoutCaptureError("binding input must contain a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze all-page source evidence and current parser predictions for a genuinely held-out Netto campaign."
    )
    parser.add_argument("binding", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = capture_heldout(_load_binding(args.binding), args.output)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
