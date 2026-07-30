from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping


WORKFLOW_VERSION = "lidl-family-weekly-corpus-promotion-v1"
PROMOTION_RESULT = "CORPUS_OBSERVATION_PROMOTED"
PROMOTION_STATUS = "PROMOTED_OBSERVATION_READY_FOR_CONTROLLED_IMPORT"
SCAN_NAME_PREFIX = "v631-"


class PromotionError(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _load_json(path: Path, label: str) -> Mapping[str, Any]:
    if not path.is_file():
        raise PromotionError(f"{label} is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromotionError(f"{label} is invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise PromotionError(f"{label} must contain an object")
    return payload


def _require_sha(value: Any, label: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise PromotionError(f"{label} must be a lowercase SHA-256")
    return text


def _parse_sha256sums(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise PromotionError("authoritative scan SHA256SUMS is missing")
    entries: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise PromotionError("invalid SHA256SUMS line")
        digest = _require_sha(parts[0], "scan checksum")
        name = parts[1].lstrip("*")
        candidate = Path(name)
        if candidate.is_absolute() or ".." in candidate.parts or len(candidate.parts) != 1:
            raise PromotionError("unsafe scan checksum path")
        if name == "SHA256SUMS" or name in entries:
            raise PromotionError("duplicate or recursive scan checksum entry")
        entries[name] = digest
    if not entries:
        raise PromotionError("authoritative scan checksum manifest is empty")
    return entries


def _verify_scan(scan_root: Path, expected_parser_sha256: str) -> tuple[Mapping[str, Any], str, list[str]]:
    sums_path = scan_root / "SHA256SUMS"
    entries = _parse_sha256sums(sums_path)
    actual_files = sorted(
        path.name
        for path in scan_root.iterdir()
        if path.is_file() and path.name != "SHA256SUMS"
    )
    if actual_files != sorted(entries):
        raise PromotionError("authoritative scan file set does not match SHA256SUMS")
    for name, expected in entries.items():
        if _sha256_file(scan_root / name) != expected:
            raise PromotionError(f"authoritative scan checksum mismatch: {name}")
    summary = _load_json(scan_root / "summary.json", "authoritative scan summary")
    if summary.get("parser_sha256") != expected_parser_sha256:
        raise PromotionError("authoritative scan parser SHA mismatch")
    if summary.get("parser_version") != "lidl-pdf-v08c-r61-shadow-v631":
        raise PromotionError("authoritative scan parser version mismatch")
    expected_counts = {
        "rows": 353,
        "physical_rows": 352,
        "accepted_physical_rows": 204,
        "review_required_rows": 148,
        "online_only_rows": 1,
    }
    for key, expected in expected_counts.items():
        if summary.get(key) != expected:
            raise PromotionError(f"authoritative scan {key} mismatch")
    return summary, _sha256_file(sums_path), actual_files


def _validate_profile(path: Path, expected_sha256: str, expected_pdf_sha256: str) -> Mapping[str, Any]:
    if _sha256_file(path) != expected_sha256:
        raise PromotionError("review profile SHA mismatch")
    profile = _load_json(path, "review profile")
    if profile.get("schema_version") != 1:
        raise PromotionError("review profile schema mismatch")
    if profile.get("status") != "independent_page_role_reviewed_product_audit_in_progress":
        raise PromotionError("review profile status mismatch")
    if profile.get("target_kind") != "weekly_physical_deals":
        raise PromotionError("review profile target kind mismatch")
    if expected_pdf_sha256 not in str(profile.get("source") or ""):
        raise PromotionError("review profile PDF identity mismatch")
    target = list(profile.get("target_pages") or [])
    baseline = list(profile.get("baseline_pages") or [])
    excluded = profile.get("excluded_page_roles") or {}
    if not isinstance(excluded, Mapping):
        raise PromotionError("review profile excluded page roles invalid")
    assigned = target + baseline
    for pages in excluded.values():
        if not isinstance(pages, list):
            raise PromotionError("review profile excluded page list invalid")
        assigned.extend(pages)
    if len(target) != 23 or len(assigned) != 69:
        raise PromotionError("review profile page counts mismatch")
    if sorted(assigned) != list(range(1, 70)) or len(set(assigned)) != 69:
        raise PromotionError("review profile must partition all 69 pages exactly once")
    return profile


def _validate_source_review(path: Path, expected_sha256: str, approval: Mapping[str, Any]) -> Mapping[str, Any]:
    if _sha256_file(path) != expected_sha256:
        raise PromotionError("source review SHA mismatch")
    review = _load_json(path, "source review")
    if review.get("schema_version") != 1:
        raise PromotionError("source review schema mismatch")
    if review.get("decision") != "approve_parser_input_refresh":
        raise PromotionError("source review decision mismatch")
    if review.get("scope") != "authoritative_staging_scan_only":
        raise PromotionError("source review scope mismatch")
    if review.get("flyer_key") != approval.get("flyer_key"):
        raise PromotionError("source review flyer key mismatch")
    if review.get("pdf_sha256") != approval.get("pdf_sha256"):
        raise PromotionError("source review PDF mismatch")
    permissions = review.get("permissions")
    if not isinstance(permissions, Mapping):
        raise PromotionError("source review permissions missing")
    expected_permissions = {
        "staging_scan": True,
        "corpus_write": False,
        "db_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "systemd_change": False,
    }
    if dict(permissions) != expected_permissions:
        raise PromotionError("source review permissions mismatch")
    return review


def _validate_approval(path: Path) -> tuple[Mapping[str, Any], str]:
    approval = _load_json(path, "corpus promotion approval")
    expected_fields = {
        "schema_version",
        "decision",
        "scope",
        "approved_at",
        "approved_by",
        "flyer_key",
        "pdf_sha256",
        "raw_sha256",
        "parser_sha256",
        "source_review_sha256",
        "review_profile_sha256",
        "staging_digest_sha256",
        "scan_expectations",
        "permissions",
        "note",
    }
    if set(approval) != expected_fields:
        raise PromotionError("corpus promotion approval field set mismatch")
    if approval.get("schema_version") != 1:
        raise PromotionError("corpus promotion approval schema mismatch")
    if approval.get("decision") != "approve_exact_corpus_observation_promotion":
        raise PromotionError("corpus promotion approval decision mismatch")
    if approval.get("scope") != "immutable_corpus_observation_append_only":
        raise PromotionError("corpus promotion approval scope mismatch")
    if approval.get("approved_by") != "Andris Rožkalns":
        raise PromotionError("corpus promotion approver mismatch")
    for key in (
        "pdf_sha256",
        "raw_sha256",
        "parser_sha256",
        "source_review_sha256",
        "review_profile_sha256",
        "staging_digest_sha256",
    ):
        _require_sha(approval.get(key), f"approval {key}")
    expected_scan = {
        "rows": 353,
        "physical_rows": 352,
        "accepted_physical_rows": 204,
        "review_required_rows": 148,
        "online_only_rows": 1,
    }
    if approval.get("scan_expectations") != expected_scan:
        raise PromotionError("corpus promotion scan expectations mismatch")
    expected_permissions = {
        "corpus_write": True,
        "canonical_root_replace": False,
        "db_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "systemd_change": False,
        "timer_install": False,
    }
    if approval.get("permissions") != expected_permissions:
        raise PromotionError("corpus promotion approval permissions mismatch")
    return approval, _sha256_file(path)


def _tree_digest(root: Path) -> str:
    rows = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        rows.append(f"{path.relative_to(root).as_posix()}|{path.stat().st_size}|{_sha256_file(path)}")
    return _sha256_bytes(("\n".join(rows) + "\n").encode("utf-8"))


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())


def _expected_promotion_files(
    *,
    staging_observation: Path,
    scan_root: Path,
    scan_files: list[str],
    promotion_bytes: bytes,
) -> dict[str, bytes | Path]:
    result: dict[str, bytes | Path] = {
        "source.json": staging_observation / "source.json",
        "observation.json": staging_observation / "observation.json",
        "source-review.json": staging_observation / "source-review.json",
        "corpus-promotion.json": promotion_bytes,
        f"scans/{scan_root.name}/SHA256SUMS": scan_root / "SHA256SUMS",
    }
    for name in scan_files:
        result[f"scans/{scan_root.name}/{name}"] = scan_root / name
    return result


def _verify_existing_target(target: Path, expected: Mapping[str, bytes | Path]) -> None:
    actual = sorted(
        path.relative_to(target).as_posix()
        for path in target.rglob("*")
        if path.is_file()
    )
    if actual != sorted(expected):
        raise PromotionError("existing corpus observation file set mismatch")
    for relative, source in expected.items():
        path = target / relative
        if isinstance(source, bytes):
            if path.read_bytes() != source:
                raise PromotionError(f"existing corpus observation collision: {relative}")
        elif _sha256_file(path) != _sha256_file(source):
            raise PromotionError(f"existing corpus observation checksum mismatch: {relative}")


def promote(
    *,
    staging_root: Path,
    corpus_root: Path,
    approval_file: Path,
    output_dir: Path,
    flyer_key: str,
    raw_sha256: str,
    parser_sha256: str,
    staging_digest_sha256: str,
) -> Mapping[str, Any]:
    approval, approval_sha = _validate_approval(approval_file)
    if approval.get("flyer_key") != flyer_key:
        raise PromotionError("approval flyer key does not match CLI target")
    if approval.get("raw_sha256") != raw_sha256:
        raise PromotionError("approval raw SHA does not match CLI target")
    if approval.get("parser_sha256") != parser_sha256:
        raise PromotionError("approval parser SHA does not match CLI target")
    if approval.get("staging_digest_sha256") != staging_digest_sha256:
        raise PromotionError("approval staging digest does not match verified host digest")

    staging_flyer = staging_root.resolve() / "flyers" / flyer_key
    corpus_flyer = corpus_root.resolve() / "flyers" / flyer_key
    staging_observation = staging_flyer / "observations" / raw_sha256
    scan_root = staging_observation / "scans" / f"{SCAN_NAME_PREFIX}{parser_sha256[:12]}"

    if not staging_flyer.is_dir() or not staging_observation.is_dir():
        raise PromotionError("exact staging flyer observation is missing")
    if not corpus_flyer.is_dir():
        raise PromotionError("matching immutable corpus flyer is missing")

    staging_pdf = staging_flyer / "source.pdf"
    corpus_pdf = corpus_flyer / "source.pdf"
    expected_pdf_sha = str(approval["pdf_sha256"])
    if _sha256_file(staging_pdf) != expected_pdf_sha:
        raise PromotionError("staging PDF SHA mismatch")
    if _sha256_file(corpus_pdf) != expected_pdf_sha:
        raise PromotionError("corpus PDF SHA mismatch")

    staging_profile = staging_flyer / "review-profile.json"
    corpus_profile = corpus_flyer / "review-profile.json"
    expected_profile_sha = str(approval["review_profile_sha256"])
    _validate_profile(staging_profile, expected_profile_sha, expected_pdf_sha)
    _validate_profile(corpus_profile, expected_profile_sha, expected_pdf_sha)
    if staging_profile.read_bytes() != corpus_profile.read_bytes():
        raise PromotionError("staging and corpus review profiles differ")

    source_path = staging_observation / "source.json"
    if _sha256_file(source_path) != raw_sha256:
        raise PromotionError("staging source JSON raw SHA mismatch")
    observation = _load_json(staging_observation / "observation.json", "staging observation metadata")
    required_observation = {
        "raw_sha256": raw_sha256,
        "source_pdf_sha256": expected_pdf_sha,
        "parser_input_identity_sha256": "5fe574a065f434e0e2ad1866d5eea79235ec0c4110d901ecf541c1c5e8678137",
        "product_binding_sha256": "5f7fe6f02be0159c8289906a9ea89006548d8ed3c7f1031c6829b09fbca585d4",
        "product_binding_count": 140,
    }
    for key, expected in required_observation.items():
        if observation.get(key) != expected:
            raise PromotionError(f"staging observation {key} mismatch")

    expected_source_review_sha = str(approval["source_review_sha256"])
    _validate_source_review(
        staging_observation / "source-review.json",
        expected_source_review_sha,
        approval,
    )

    summary, scan_sums_sha, scan_files = _verify_scan(scan_root, parser_sha256)
    if summary.get("flyer_key") != flyer_key:
        raise PromotionError("authoritative scan flyer key mismatch")
    source_summary = summary.get("source")
    if not isinstance(source_summary, Mapping):
        raise PromotionError("authoritative scan source metadata missing")
    if source_summary.get("pdf_sha256") != expected_pdf_sha:
        raise PromotionError("authoritative scan PDF SHA mismatch")
    if source_summary.get("raw_sha256") != raw_sha256:
        raise PromotionError("authoritative scan raw SHA mismatch")

    staging_digest = staging_digest_sha256

    promotion = {
        "schema_version": 1,
        "workflow_version": WORKFLOW_VERSION,
        "status": PROMOTION_STATUS,
        "approved_at": approval["approved_at"],
        "approved_by": approval["approved_by"],
        "flyer_key": flyer_key,
        "source": {
            "pdf_sha256": expected_pdf_sha,
            "raw_sha256": raw_sha256,
            "parser_input_identity_sha256": observation["parser_input_identity_sha256"],
            "product_binding_sha256": observation["product_binding_sha256"],
            "product_binding_count": observation["product_binding_count"],
        },
        "review": {
            "source_review_sha256": expected_source_review_sha,
            "review_profile_sha256": expected_profile_sha,
            "corpus_promotion_approval_sha256": approval_sha,
        },
        "scan": {
            "name": scan_root.name,
            "parser_version": summary["parser_version"],
            "parser_sha256": parser_sha256,
            "rows": summary["rows"],
            "physical_rows": summary["physical_rows"],
            "accepted_physical_rows": summary["accepted_physical_rows"],
            "review_required_rows": summary["review_required_rows"],
            "online_only_rows": summary["online_only_rows"],
            "sha256sums_sha256": scan_sums_sha,
        },
        "provenance": {
            "staging_digest_sha256": staging_digest,
            "staging_observation": f"flyers/{flyer_key}/observations/{raw_sha256}",
        },
        "permissions": dict(approval["permissions"]),
    }
    promotion_bytes = _canonical_json_bytes(promotion)
    expected_files = _expected_promotion_files(
        staging_observation=staging_observation,
        scan_root=scan_root,
        scan_files=scan_files,
        promotion_bytes=promotion_bytes,
    )

    target = corpus_flyer / "observations" / raw_sha256
    created = False
    if target.exists():
        if not target.is_dir():
            raise PromotionError("corpus observation target is not a directory")
        _verify_existing_target(target, expected_files)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{raw_sha256}.tmp-", dir=target.parent))
        try:
            for relative, source in expected_files.items():
                destination = temporary / relative
                if isinstance(source, bytes):
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with destination.open("xb") as handle:
                        handle.write(source)
                        handle.flush()
                        os.fsync(handle.fileno())
                else:
                    _copy_file(source, destination)
            _verify_existing_target(temporary, expected_files)
            os.replace(temporary, target)
            created = True
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    target_digest = _tree_digest(target)
    status = {
        "schema_version": 1,
        "workflow_version": WORKFLOW_VERSION,
        "result": PROMOTION_RESULT,
        "reason": "exact_staged_observation_appended_to_immutable_corpus",
        "flyer_key": flyer_key,
        "corpus_observation": str(target),
        "created": created,
        "reused": not created,
        "target_digest_sha256": target_digest,
        "promotion_manifest_sha256": _sha256_bytes(promotion_bytes),
        "source": promotion["source"],
        "review": promotion["review"],
        "scan": promotion["scan"],
        "corpus_write": True,
        "canonical_root_replace": False,
        "db_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "systemd_change": False,
        "timer_install": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "promotion-status.json"
    temporary_status = output_dir / f".promotion-status.json.tmp-{os.getpid()}"
    temporary_status.write_bytes(_canonical_json_bytes(status))
    os.replace(temporary_status, status_path)
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Promote one exact Lidl staging observation into the immutable corpus")
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--approval-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--flyer-key", required=True)
    parser.add_argument("--raw-sha256", required=True)
    parser.add_argument("--parser-sha256", required=True)
    parser.add_argument("--staging-digest-sha256", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        status = promote(
            staging_root=args.staging_root,
            corpus_root=args.corpus_root,
            approval_file=args.approval_file,
            output_dir=args.output_dir,
            flyer_key=args.flyer_key,
            raw_sha256=_require_sha(args.raw_sha256, "raw SHA"),
            parser_sha256=_require_sha(args.parser_sha256, "parser SHA"),
            staging_digest_sha256=_require_sha(args.staging_digest_sha256, "staging digest SHA"),
        )
    except PromotionError as exc:
        print(f"ERROR={exc}")
        print("RESULT=CORPUS_PROMOTION_BLOCKED")
        return 2
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    print(f"RESULT={PROMOTION_RESULT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
