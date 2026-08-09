#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
import re
from typing import Any, Mapping

PACK_STRATEGY = "netto_heldout_blind_source_card_review_pack_v1"
LEDGER_STRATEGY = "netto_heldout_blind_source_card_review_ledger_v1"
EXPECTED_PYMUPDF_VERSION = "1.28.0"
RENDER_DPI = 144
STORE_ID = "5659"
SCOPE = "family_primary_netto"
OWNERSHIP_CLASSES = ("single_source", "mixed_source", "excluded_control")
SCOPE_CLASSES = ("in_scope", "excluded", "ambiguous")


class HeldoutBlindReviewPackError(ValueError):
    pass


def sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise HeldoutBlindReviewPackError(f"input must be a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HeldoutBlindReviewPackError(f"invalid UTF-8 JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise HeldoutBlindReviewPackError(f"JSON input must contain an object: {path}")
    return payload


def require_sha256(value: str, label: str) -> str:
    text = str(value).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise HeldoutBlindReviewPackError(f"{label} must be a SHA256")
    return text


def write_create_only(path: Path, payload: bytes) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise HeldoutBlindReviewPackError(
            f"output member already exists: {path}"
        ) from exc
    return sha256(payload).hexdigest(), len(payload)


def text_spans(page: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = page.get_text("dict")
    for block_index, block in enumerate(text.get("blocks", [])):
        if block.get("type") != 0:
            continue
        for line_index, line in enumerate(block.get("lines", [])):
            for span_index, span in enumerate(line.get("spans", [])):
                value = re.sub(r"\s+", " ", str(span.get("text") or "")).strip()
                bbox = span.get("bbox")
                if not value or not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                    continue
                rows.append(
                    {
                        "block_index": block_index,
                        "line_index": line_index,
                        "span_index": span_index,
                        "text": value,
                        "bbox": [round(float(bbox[index]), 3) for index in range(4)],
                        "size": round(float(span.get("size") or 0.0), 3),
                        "font": str(span.get("font") or ""),
                        "color": int(span.get("color") or 0),
                        "flags": int(span.get("flags") or 0),
                    }
                )
    return sorted(
        rows,
        key=lambda row: (
            row["bbox"][1],
            row["bbox"][0],
            row["block_index"],
            row["line_index"],
            row["span_index"],
        ),
    )


def _validate_safe_capture(
    capture_root: Path,
    *,
    expected_commit: str,
    expected_campaign: str,
    expected_valid_from: str,
    expected_valid_until: str,
    expected_source_sha256: str,
    expected_pdf_sha256: str,
    expected_freeze_manifest_sha256: str,
    expected_page_count: int,
) -> tuple[Path, dict[str, Any]]:
    if capture_root.is_symlink() or not capture_root.is_dir():
        raise HeldoutBlindReviewPackError("capture root must be a regular directory")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise HeldoutBlindReviewPackError("expected commit must be exact lowercase SHA")
    if expected_page_count <= 0:
        raise HeldoutBlindReviewPackError("expected page count must be positive")

    expected_source_sha256 = require_sha256(
        expected_source_sha256, "expected source identity"
    )
    expected_pdf_sha256 = require_sha256(expected_pdf_sha256, "expected PDF")
    expected_freeze_manifest_sha256 = require_sha256(
        expected_freeze_manifest_sha256, "expected freeze manifest"
    )
    expected_pdf_rel = (
        f"source/netto/{STORE_ID}-{expected_campaign}-{expected_pdf_sha256}.pdf"
    )
    expected_files = {
        "github-capture-result.json",
        "live-source.json",
        "selected-binding.json",
        "capture/freeze-manifest.json",
        "capture/freeze-receipt.json",
        "capture/blind-review-template.json",
        expected_pdf_rel,
    }
    actual_files = {
        path.relative_to(capture_root).as_posix()
        for path in capture_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if actual_files != expected_files:
        raise HeldoutBlindReviewPackError(
            f"safe capture member set mismatch: "
            f"missing={sorted(expected_files - actual_files)} "
            f"extra={sorted(actual_files - expected_files)}"
        )
    if any(path.is_symlink() for path in capture_root.rglob("*")):
        raise HeldoutBlindReviewPackError("safe capture must not contain symlinks")

    result = load_json(capture_root / "github-capture-result.json")
    live = load_json(capture_root / "live-source.json")
    selected = load_json(capture_root / "selected-binding.json")
    freeze = load_json(capture_root / "capture" / "freeze-manifest.json")
    receipt = load_json(capture_root / "capture" / "freeze-receipt.json")
    template = load_json(capture_root / "capture" / "blind-review-template.json")

    expected_window = {"start": expected_valid_from, "end": expected_valid_until}

    if result.get("strategy") != "netto_heldout_github_capture_v1":
        raise HeldoutBlindReviewPackError("upstream capture strategy mismatch")
    if result.get("result") != "PASS" or result.get("registered_commit") != expected_commit:
        raise HeldoutBlindReviewPackError("upstream capture result/commit mismatch")
    if result.get("campaign_key") != expected_campaign:
        raise HeldoutBlindReviewPackError("upstream capture campaign mismatch")
    for key in (
        "database_write_performed",
        "review_write_performed",
        "deployment_performed",
        "scheduler_change_performed",
    ):
        if result.get(key) is not False:
            raise HeldoutBlindReviewPackError(f"upstream unsafe result flag: {key}")
    if result.get("truth_available_at_freeze") is not False:
        raise HeldoutBlindReviewPackError("upstream capture was not truth-blind")
    if result.get("review_only") is not True or result.get("promotion_ready") is not False:
        raise HeldoutBlindReviewPackError("upstream capture safety state mismatch")

    if live.get("strategy") != "netto_heldout_github_live_source_v1":
        raise HeldoutBlindReviewPackError("upstream live-source strategy mismatch")
    if live.get("store_external_id") != STORE_ID or live.get("scope") != SCOPE:
        raise HeldoutBlindReviewPackError("upstream live source store/scope mismatch")
    if live.get("campaign_key") != expected_campaign:
        raise HeldoutBlindReviewPackError("upstream live source campaign mismatch")
    if live.get("campaign_window") != expected_window:
        raise HeldoutBlindReviewPackError("upstream live source validity mismatch")
    for key in (
        "database_write_performed",
        "review_write_performed",
        "deployment_performed",
        "scheduler_change_performed",
    ):
        if live.get(key) is not False:
            raise HeldoutBlindReviewPackError(f"upstream unsafe live-source flag: {key}")

    binding = selected.get("binding")
    if not isinstance(binding, Mapping):
        raise HeldoutBlindReviewPackError("selected binding object missing")
    if selected.get("strategy") != "netto_heldout_verified_source_selector_v1":
        raise HeldoutBlindReviewPackError("selected binding strategy mismatch")
    if selected.get("campaign_key") != expected_campaign:
        raise HeldoutBlindReviewPackError("selected binding campaign mismatch")
    if selected.get("campaign_window") != expected_window:
        raise HeldoutBlindReviewPackError("selected binding validity mismatch")
    if selected.get("evidence_identity_sha256") != expected_source_sha256:
        raise HeldoutBlindReviewPackError("selected source identity mismatch")
    if binding.get("store_external_id") != STORE_ID or binding.get("scope") != SCOPE:
        raise HeldoutBlindReviewPackError("selected binding store/scope mismatch")
    if binding.get("valid_from") != expected_valid_from or binding.get("valid_until") != expected_valid_until:
        raise HeldoutBlindReviewPackError("selected binding date mismatch")
    if binding.get("pdf_sha256") != expected_pdf_sha256:
        raise HeldoutBlindReviewPackError("selected binding PDF mismatch")
    if binding.get("evidence_status") != "pdf_bound":
        raise HeldoutBlindReviewPackError("selected binding is not pdf_bound")
    if selected.get("review_only") is not True or selected.get("promotion_ready") is not False:
        raise HeldoutBlindReviewPackError("selected binding safety state mismatch")

    if freeze.get("schema_version") != 1 or freeze.get("protocol") != "netto-heldout-ownership-v1":
        raise HeldoutBlindReviewPackError("freeze manifest protocol mismatch")
    if freeze.get("store_external_id") != STORE_ID:
        raise HeldoutBlindReviewPackError("freeze manifest store mismatch")
    if freeze.get("campaign_key") != expected_campaign or freeze.get("campaign_window") != expected_window:
        raise HeldoutBlindReviewPackError("freeze manifest campaign mismatch")
    if freeze.get("source_sha256") != expected_source_sha256:
        raise HeldoutBlindReviewPackError("freeze manifest source mismatch")
    if canonical_json_sha256(freeze) != expected_freeze_manifest_sha256:
        raise HeldoutBlindReviewPackError("canonical freeze manifest SHA mismatch")
    if freeze.get("truth_sha256") is not None or freeze.get("adjudication_sha256") is not None:
        raise HeldoutBlindReviewPackError("freeze manifest contains truth/adjudication")
    if freeze.get("review_only") is not True or freeze.get("promotion_ready") is not False:
        raise HeldoutBlindReviewPackError("freeze manifest safety state mismatch")

    if receipt.get("source_sha256") != expected_source_sha256:
        raise HeldoutBlindReviewPackError("freeze receipt source identity mismatch")
    if receipt.get("freeze_manifest_sha256") != expected_freeze_manifest_sha256:
        raise HeldoutBlindReviewPackError("freeze receipt manifest identity mismatch")
    if receipt.get("truth_available_at_freeze") is not False:
        raise HeldoutBlindReviewPackError("freeze receipt was not truth-blind")
    if receipt.get("review_only") is not True or receipt.get("promotion_ready") is not False:
        raise HeldoutBlindReviewPackError("freeze receipt safety state mismatch")

    if template.get("campaign_key") != expected_campaign:
        raise HeldoutBlindReviewPackError("blank template campaign mismatch")
    if template.get("source_sha256") != expected_source_sha256:
        raise HeldoutBlindReviewPackError("blank template source identity mismatch")
    if template.get("freeze_manifest_sha256") != expected_freeze_manifest_sha256:
        raise HeldoutBlindReviewPackError("blank template freeze identity mismatch")
    if template.get("page_count") != expected_page_count:
        raise HeldoutBlindReviewPackError("blank template page count mismatch")
    if template.get("parser_predictions_included") is not False:
        raise HeldoutBlindReviewPackError("review template exposed parser data")
    if template.get("expected_truth_included") is not False:
        raise HeldoutBlindReviewPackError("review template exposed expected truth")
    pages = template.get("pages")
    if not isinstance(pages, list) or len(pages) != expected_page_count:
        raise HeldoutBlindReviewPackError("blank template pages are incomplete")
    expected_page_numbers = list(range(1, expected_page_count + 1))
    if [row.get("page_number") for row in pages if isinstance(row, Mapping)] != expected_page_numbers:
        raise HeldoutBlindReviewPackError("blank template page identities mismatch")
    if any(not isinstance(row, Mapping) or row.get("source_cards") != [] for row in pages):
        raise HeldoutBlindReviewPackError("upstream source-card template is not blank")

    pdf_path = capture_root / expected_pdf_rel
    if sha_file(pdf_path) != expected_pdf_sha256:
        raise HeldoutBlindReviewPackError("frozen source PDF SHA mismatch")

    return pdf_path, {
        "campaign_key": expected_campaign,
        "campaign_window": expected_window,
        "source_sha256": expected_source_sha256,
        "source_pdf_sha256": expected_pdf_sha256,
        "freeze_manifest_sha256": expected_freeze_manifest_sha256,
        "page_count": expected_page_count,
        "upstream_capture_commit": expected_commit,
    }


def generate_pack(
    capture_root: Path,
    output: Path,
    *,
    expected_commit: str,
    expected_campaign: str,
    expected_valid_from: str,
    expected_valid_until: str,
    expected_source_sha256: str,
    expected_pdf_sha256: str,
    expected_freeze_manifest_sha256: str,
    expected_page_count: int,
    upstream_run_id: int,
    upstream_artifact_name: str,
    upstream_artifact_digest: str,
) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise HeldoutBlindReviewPackError("output directory must be create-only")
    if upstream_run_id <= 0 or not upstream_artifact_name.strip():
        raise HeldoutBlindReviewPackError("upstream artifact identity is required")
    digest_text = str(upstream_artifact_digest).strip().lower()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest_text):
        raise HeldoutBlindReviewPackError("upstream artifact digest must be sha256:<hex>")

    version = importlib.metadata.version("PyMuPDF")
    if version != EXPECTED_PYMUPDF_VERSION:
        raise HeldoutBlindReviewPackError(
            f"PyMuPDF runtime mismatch: expected {EXPECTED_PYMUPDF_VERSION}, got {version}"
        )

    pdf_path, binding = _validate_safe_capture(
        capture_root,
        expected_commit=expected_commit,
        expected_campaign=expected_campaign,
        expected_valid_from=expected_valid_from,
        expected_valid_until=expected_valid_until,
        expected_source_sha256=expected_source_sha256,
        expected_pdf_sha256=expected_pdf_sha256,
        expected_freeze_manifest_sha256=expected_freeze_manifest_sha256,
        expected_page_count=expected_page_count,
    )

    import pymupdf

    output.mkdir(parents=True, mode=0o700)
    members: list[dict[str, Any]] = []
    page_rows: list[dict[str, Any]] = []
    ledger_pages: list[dict[str, Any]] = []

    document = pymupdf.open(pdf_path)
    try:
        if document.page_count != expected_page_count:
            raise HeldoutBlindReviewPackError("frozen PDF page count mismatch")
        matrix = pymupdf.Matrix(RENDER_DPI / 72.0, RENDER_DPI / 72.0)
        for page_number in range(1, document.page_count + 1):
            page = document.load_page(page_number - 1)
            source_rotation = int(page.rotation)
            if source_rotation:
                page.set_rotation(0)
            width = float(page.cropbox.width)
            height = float(page.cropbox.height)
            if width <= 0 or height <= 0:
                raise HeldoutBlindReviewPackError("invalid unrotated page dimensions")

            png_member = f"pages/page-{page_number:03d}.png"
            text_member = f"pages/page-{page_number:03d}.json"
            pixmap = page.get_pixmap(
                matrix=matrix,
                clip=pymupdf.Rect(0.0, 0.0, width, height),
                alpha=False,
            )
            png = pixmap.tobytes("png")
            png_sha, png_size = write_create_only(output / png_member, png)

            source_text = {
                "schema_version": 1,
                "campaign_key": binding["campaign_key"],
                "page_number": page_number,
                "source_pdf_sha256": binding["source_pdf_sha256"],
                "coordinate_space": "unrotated_page_points",
                "page_width_points": round(width, 3),
                "page_height_points": round(height, 3),
                "text_spans": text_spans(page),
            }
            text_payload = json_bytes(source_text)
            text_sha, text_size = write_create_only(output / text_member, text_payload)
            members.extend(
                [
                    {
                        "path": png_member,
                        "sha256": png_sha,
                        "bytes": png_size,
                        "kind": "page_context_png",
                    },
                    {
                        "path": text_member,
                        "sha256": text_sha,
                        "bytes": text_size,
                        "kind": "page_source_text_json",
                    },
                ]
            )
            page_rows.append(
                {
                    "page_number": page_number,
                    "source_rotation": source_rotation,
                    "page_width_points": round(width, 3),
                    "page_height_points": round(height, 3),
                    "context_image": png_member,
                    "context_image_sha256": png_sha,
                    "source_text": text_member,
                    "source_text_sha256": text_sha,
                }
            )
            ledger_pages.append(
                {
                    "page_number": page_number,
                    "page_width_points": round(width, 3),
                    "page_height_points": round(height, 3),
                    "source_cards": [],
                }
            )
    finally:
        document.close()

    ledger_name = "source-card-review-ledger.blank.json"
    ledger = {
        "schema_version": 1,
        "strategy": LEDGER_STRATEGY,
        "campaign_key": binding["campaign_key"],
        "campaign_window": binding["campaign_window"],
        "store_external_id": STORE_ID,
        "scope": SCOPE,
        "source_sha256": binding["source_sha256"],
        "source_pdf_sha256": binding["source_pdf_sha256"],
        "freeze_manifest_sha256": binding["freeze_manifest_sha256"],
        "coordinate_space": "unrotated_page_points",
        "page_count": expected_page_count,
        "review_state": "blank_independent_source_card_review",
        "reviewer_card_contract": {
            "reviewer_card_id": "stable pNNN-cNNN identifier assigned by the independent reviewer",
            "rect_points": ["x0", "y0", "x1", "y1"],
            "ownership_class": list(OWNERSHIP_CLASSES),
            "scope_classification": list(SCOPE_CLASSES),
            "reviewer_confidence": ["high", "medium", "low"],
            "ambiguity_note": "optional source-only note; required when scope or boundary is ambiguous",
        },
        "parser_predictions_included": False,
        "expected_truth_included": False,
        "pages": ledger_pages,
    }
    ledger_payload = json_bytes(ledger)
    ledger_sha, ledger_size = write_create_only(output / ledger_name, ledger_payload)
    members.append(
        {
            "path": ledger_name,
            "sha256": ledger_sha,
            "bytes": ledger_size,
            "kind": "blank_independent_source_card_review_ledger",
        }
    )

    upstream = {
        "workflow_run_id": upstream_run_id,
        "artifact_name": upstream_artifact_name,
        "artifact_digest": digest_text,
        "registered_commit": binding["upstream_capture_commit"],
    }
    manifest = {
        "schema_version": 1,
        "strategy": PACK_STRATEGY,
        "campaign_key": binding["campaign_key"],
        "campaign_window": binding["campaign_window"],
        "store_external_id": STORE_ID,
        "scope": SCOPE,
        "source_sha256": binding["source_sha256"],
        "source_pdf_sha256": binding["source_pdf_sha256"],
        "freeze_manifest_sha256": binding["freeze_manifest_sha256"],
        "upstream_capture": upstream,
        "pymupdf_version": version,
        "render_dpi": RENDER_DPI,
        "coordinate_space": "unrotated_page_points",
        "page_count": expected_page_count,
        "blind_review_contract": {
            "source_pages_only": True,
            "source_text_only": True,
            "presegmented_review_units": False,
            "parser_predictions_included": False,
            "expected_truth_included": False,
            "automatic_approval_enabled": False,
            "automatic_publish_enabled": False,
            "database_write_performed": False,
            "review_write_performed": False,
            "deployment_performed": False,
        },
        "blank_review_ledger": ledger_name,
        "blank_review_ledger_sha256": ledger_sha,
        "pages": page_rows,
        "members": sorted(members, key=lambda row: row["path"]),
    }
    manifest_payload = json_bytes(manifest)
    manifest_sha, _ = write_create_only(output / "manifest.json", manifest_payload)

    sums = [
        f"{row['sha256']}  {row['path']}"
        for row in sorted(members, key=lambda row: row["path"])
    ]
    sums.append(f"{manifest_sha}  manifest.json")
    write_create_only(
        output / "SHA256SUMS",
        ("\n".join(sums) + "\n").encode("utf-8"),
    )
    return {**manifest, "manifest_sha256": manifest_sha}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a source-only blind card-boundary review pack from an exact "
            "held-out capture artifact that has already been safely allowlist-extracted."
        )
    )
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-campaign", required=True)
    parser.add_argument("--expected-valid-from", required=True)
    parser.add_argument("--expected-valid-until", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--expected-pdf-sha256", required=True)
    parser.add_argument("--expected-freeze-manifest-sha256", required=True)
    parser.add_argument("--expected-page-count", type=int, required=True)
    parser.add_argument("--upstream-run-id", type=int, required=True)
    parser.add_argument("--upstream-artifact-name", required=True)
    parser.add_argument("--upstream-artifact-digest", required=True)
    args = parser.parse_args()

    payload = generate_pack(
        args.capture_root,
        args.output,
        expected_commit=args.expected_commit,
        expected_campaign=args.expected_campaign,
        expected_valid_from=args.expected_valid_from,
        expected_valid_until=args.expected_valid_until,
        expected_source_sha256=args.expected_source_sha256,
        expected_pdf_sha256=args.expected_pdf_sha256,
        expected_freeze_manifest_sha256=args.expected_freeze_manifest_sha256,
        expected_page_count=args.expected_page_count,
        upstream_run_id=args.upstream_run_id,
        upstream_artifact_name=args.upstream_artifact_name,
        upstream_artifact_digest=args.upstream_artifact_digest,
    )
    print(
        json.dumps(
            {
                "strategy": payload["strategy"],
                "campaign_key": payload["campaign_key"],
                "page_count": payload["page_count"],
                "manifest_sha256": payload["manifest_sha256"],
                "blank_review_ledger_sha256": payload["blank_review_ledger_sha256"],
                "parser_predictions_included": False,
                "expected_truth_included": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
