from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping


WORKFLOW_VERSION = "lidl-gate-b-family-promotion-v1"
PARSER_VERSION = "lidl-pdf-v08c-r61-shadow-v631"


class GateBPromotionError(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise GateBPromotionError(f"{label} is missing or unsafe: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateBPromotionError(f"{label} is invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise GateBPromotionError(f"{label} must contain an object")
    return payload


def _require_sha(value: Any, label: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise GateBPromotionError(f"{label} must be a lowercase SHA-256")
    return text


def canonical_scan_name(parser_sha256: str) -> str:
    parser_sha256 = _require_sha(parser_sha256, "parser SHA")
    return f"scan-v631-{parser_sha256[:12]}"


def source_observed_at(source_json: bytes) -> datetime:
    """Return a deterministic source-bound timestamp, never wall clock time."""
    try:
        payload = json.loads(source_json)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateBPromotionError("source JSON is invalid") from exc
    if not isinstance(payload, Mapping):
        raise GateBPromotionError("source JSON must contain an object")
    raw = payload.get("dateTime")
    if not isinstance(raw, str) or not raw.strip():
        raise GateBPromotionError("source JSON has no deterministic dateTime")
    text = raw.strip().replace("Z", "+00:00")
    try:
        observed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise GateBPromotionError("source dateTime is invalid") from exc
    if observed.tzinfo is None:
        raise GateBPromotionError("source dateTime must include a timezone")
    return observed.astimezone(timezone.utc)


def _parse_sha256s(scan_root: Path) -> dict[str, str]:
    sums = scan_root / "SHA256SUMS"
    if not sums.is_file() or sums.is_symlink():
        raise GateBPromotionError("scan SHA256SUMS is missing or unsafe")
    entries: dict[str, str] = {}
    for raw in sums.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        parts = raw.split("  ", 1)
        if len(parts) != 2:
            raise GateBPromotionError("invalid SHA256SUMS line")
        digest = _require_sha(parts[0], "scan member SHA")
        name = parts[1]
        candidate = Path(name)
        if candidate.is_absolute() or ".." in candidate.parts or len(candidate.parts) != 1:
            raise GateBPromotionError("unsafe scan member path")
        if name == "SHA256SUMS" or name in entries:
            raise GateBPromotionError("duplicate/recursive scan member")
        entries[name] = digest
    actual = sorted(
        p.name for p in scan_root.iterdir()
        if p.is_file() and not p.is_symlink() and p.name != "SHA256SUMS"
    )
    if actual != sorted(entries):
        raise GateBPromotionError("scan file set does not match SHA256SUMS")
    for name, digest in entries.items():
        if _sha256_file(scan_root / name) != digest:
            raise GateBPromotionError(f"scan checksum mismatch: {name}")
    return entries


def _tree_digest(root: Path) -> str:
    rows: list[str] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink()):
        rows.append(f"{path.relative_to(root).as_posix()}|{path.stat().st_size}|{_sha256_file(path)}")
    return _sha256_bytes(("\n".join(rows) + "\n").encode("utf-8"))


def _validate_profile(path: Path, *, pdf_sha256: str, page_count: int) -> Mapping[str, Any]:
    profile = _load_json(path, "review profile")
    if profile.get("schema_version") != 1:
        raise GateBPromotionError("review profile schema mismatch")
    if profile.get("target_kind") != "weekly_physical_deals":
        raise GateBPromotionError("review profile target kind mismatch")
    if "reviewed" not in str(profile.get("status") or ""):
        raise GateBPromotionError("review profile is not independently reviewed")
    if pdf_sha256 not in str(profile.get("source") or ""):
        raise GateBPromotionError("review profile PDF identity mismatch")
    assigned: list[int] = []
    for key in ("target_pages", "baseline_pages"):
        values = profile.get(key) or []
        if not isinstance(values, list):
            raise GateBPromotionError(f"review profile {key} is invalid")
        assigned.extend(values)
    excluded = profile.get("excluded_page_roles") or {}
    if not isinstance(excluded, Mapping):
        raise GateBPromotionError("review profile excluded roles are invalid")
    for values in excluded.values():
        if not isinstance(values, list):
            raise GateBPromotionError("review profile excluded page list is invalid")
        assigned.extend(values)
    if any(isinstance(v, bool) or not isinstance(v, int) for v in assigned):
        raise GateBPromotionError("review profile page must be an integer")
    if len(assigned) != len(set(assigned)) or sorted(assigned) != list(range(1, page_count + 1)):
        raise GateBPromotionError("review profile must partition every page exactly once")
    return profile


def _validate_scan(
    scan_root: Path,
    *,
    flyer_key: str,
    pdf_sha256: str,
    raw_sha256: str,
    parser_sha256: str,
) -> Mapping[str, Any]:
    if not scan_root.is_dir() or scan_root.is_symlink():
        raise GateBPromotionError("staged scan is missing or unsafe")
    expected_name = canonical_scan_name(parser_sha256)
    if scan_root.name != expected_name:
        raise GateBPromotionError("canonical scan name mismatch")
    _parse_sha256s(scan_root)
    summary = _load_json(scan_root / "summary.json", "scan summary")
    if summary.get("flyer_key") != flyer_key:
        raise GateBPromotionError("scan flyer key mismatch")
    if summary.get("scan") != expected_name:
        raise GateBPromotionError("scan summary name mismatch")
    if summary.get("parser_version") != PARSER_VERSION:
        raise GateBPromotionError("scan parser version mismatch")
    if summary.get("parser_sha256") != parser_sha256:
        raise GateBPromotionError("scan parser SHA mismatch")
    source = summary.get("source")
    if not isinstance(source, Mapping):
        raise GateBPromotionError("scan source binding missing")
    if source.get("pdf_sha256") != pdf_sha256 or source.get("raw_sha256") != raw_sha256:
        raise GateBPromotionError("scan source binding mismatch")
    # Counts are intentionally data-driven. Never encode historical B15H4 constants.
    for key in ("rows", "physical_rows", "accepted_physical_rows", "review_required_rows", "online_only_rows"):
        value = summary.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise GateBPromotionError(f"scan {key} is invalid")
    scanned_at = str(summary.get("scanned_at") or "")
    if not scanned_at:
        raise GateBPromotionError("scan has no source-bound timestamp")
    return summary


def _validate_approval(
    path: Path,
    *,
    flyer_key: str,
    pdf_sha256: str,
    raw_sha256: str,
    parser_sha256: str,
    scan_name: str,
    scan_digest: str,
    profile_sha256: str,
    summary: Mapping[str, Any],
) -> Mapping[str, Any]:
    approval = _load_json(path, "Gate B promotion approval")
    fields = {
        "schema_version", "decision", "scope", "approved_by", "approved_at", "note",
        "flyer_key", "pdf_sha256", "raw_sha256", "parser_sha256", "scan_name",
        "scan_tree_sha256", "review_profile_sha256", "scan_expectations", "permissions",
    }
    if set(approval) != fields:
        raise GateBPromotionError("promotion approval field set mismatch")
    if approval.get("schema_version") != 1 or approval.get("decision") != "approve_gate_b_family_promotion":
        raise GateBPromotionError("promotion approval decision mismatch")
    if approval.get("scope") != "canonical_scan_profile_create_once":
        raise GateBPromotionError("promotion approval scope mismatch")
    if not str(approval.get("approved_by") or "").strip() or not str(approval.get("approved_at") or "").strip() or not str(approval.get("note") or "").strip():
        raise GateBPromotionError("promotion approval attribution is incomplete")
    expected = {
        "flyer_key": flyer_key, "pdf_sha256": pdf_sha256, "raw_sha256": raw_sha256,
        "parser_sha256": parser_sha256, "scan_name": scan_name,
        "scan_tree_sha256": scan_digest, "review_profile_sha256": profile_sha256,
    }
    for key, value in expected.items():
        if approval.get(key) != value:
            raise GateBPromotionError(f"promotion approval {key} mismatch")
    expected_counts = {
        key: summary[key]
        for key in ("rows", "physical_rows", "accepted_physical_rows", "review_required_rows", "online_only_rows")
    }
    if approval.get("scan_expectations") != expected_counts:
        raise GateBPromotionError("promotion approval scan expectations mismatch")
    permissions = {
        "corpus_write": True, "replace_existing": False, "db_write": False,
        "review_write": False, "auto_approve": False, "auto_publish": False,
        "systemd_change": False, "timer_install": False, "production_deploy": False,
    }
    if approval.get("permissions") != permissions:
        raise GateBPromotionError("promotion approval permissions are unsafe")
    return approval


def build_plan(
    *,
    frozen_family: Path,
    staged_scan: Path,
    reviewed_profile: Path,
    approval_file: Path,
    parser_sha256: str,
) -> dict[str, Any]:
    frozen_family = frozen_family.resolve()
    if not frozen_family.is_dir() or frozen_family.is_symlink():
        raise GateBPromotionError("frozen family is missing or unsafe")
    source_pdf = frozen_family / "source.pdf"
    source_json = frozen_family / "source.json"
    if not source_pdf.is_file() or source_pdf.is_symlink() or not source_json.is_file() or source_json.is_symlink():
        raise GateBPromotionError("frozen source files are incomplete or unsafe")
    pdf_sha = _sha256_file(source_pdf)
    raw_sha = _sha256_file(source_json)
    parser_sha256 = _require_sha(parser_sha256, "parser SHA")
    summary = _validate_scan(
        staged_scan,
        flyer_key=frozen_family.name,
        pdf_sha256=pdf_sha,
        raw_sha256=raw_sha,
        parser_sha256=parser_sha256,
    )
    source_payload = json.loads(source_json.read_text(encoding="utf-8"))
    flyer = source_payload.get("flyer") if isinstance(source_payload, Mapping) else None
    pages = flyer.get("pages") if isinstance(flyer, Mapping) else None
    if not isinstance(pages, list) or not pages:
        raise GateBPromotionError("frozen source page count is unavailable")
    _validate_profile(reviewed_profile, pdf_sha256=pdf_sha, page_count=len(pages))
    profile_sha = _sha256_file(reviewed_profile)
    scan_digest = _tree_digest(staged_scan)
    scan_name = canonical_scan_name(parser_sha256)
    _validate_approval(
        approval_file,
        flyer_key=frozen_family.name,
        pdf_sha256=pdf_sha,
        raw_sha256=raw_sha,
        parser_sha256=parser_sha256,
        scan_name=scan_name,
        scan_digest=scan_digest,
        profile_sha256=profile_sha,
        summary=summary,
    )

    scan_target = frozen_family / "scans" / scan_name
    profile_target = frozen_family / "review-profile.json"
    if scan_target.exists():
        if not scan_target.is_dir() or scan_target.is_symlink() or _tree_digest(scan_target) != scan_digest:
            raise GateBPromotionError("occupied canonical scan destination is not byte-identical")
        scan_action = "REUSE_IDENTICAL"
    else:
        scan_action = "CREATE"
    if profile_target.exists():
        if not profile_target.is_file() or profile_target.is_symlink() or _sha256_file(profile_target) != profile_sha:
            raise GateBPromotionError("occupied review-profile destination is not byte-identical")
        profile_action = "REUSE_IDENTICAL"
    else:
        profile_action = "CREATE"
    return {
        "schema_version": 1,
        "workflow_version": WORKFLOW_VERSION,
        "result": "READY_TO_PROMOTE" if "CREATE" in (scan_action, profile_action) else "NO_OP_IDENTICAL",
        "flyer_key": frozen_family.name,
        "source": {"pdf_sha256": pdf_sha, "raw_sha256": raw_sha, "page_count": len(pages)},
        "parser": {"version": PARSER_VERSION, "sha256": parser_sha256},
        "scan": {"name": scan_name, "tree_sha256": scan_digest, "action": scan_action},
        "review_profile": {"sha256": profile_sha, "action": profile_action},
        "scan_expectations": {key: summary[key] for key in ("rows", "physical_rows", "accepted_physical_rows", "review_required_rows", "online_only_rows")},
        "corpus_write_authorized": True,
        "db_write": False,
        "review_write": False,
        "auto_approve": False,
        "auto_publish": False,
        "production_deploy": False,
        "systemd_change": False,
    }


def apply_plan(
    *,
    frozen_family: Path,
    staged_scan: Path,
    reviewed_profile: Path,
    approval_file: Path,
    parser_sha256: str,
) -> dict[str, Any]:
    plan = build_plan(
        frozen_family=frozen_family,
        staged_scan=staged_scan,
        reviewed_profile=reviewed_profile,
        approval_file=approval_file,
        parser_sha256=parser_sha256,
    )
    frozen_family = frozen_family.resolve()
    scan_target = frozen_family / "scans" / plan["scan"]["name"]
    profile_target = frozen_family / "review-profile.json"
    writes = 0
    if plan["scan"]["action"] == "CREATE":
        scans_root = frozen_family / "scans"
        scans_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".gate-b-scan-", dir=scans_root))
        os.chmod(temporary, 0o700)
        try:
            for source in sorted(p for p in staged_scan.iterdir() if p.is_file() and not p.is_symlink()):
                target = temporary / source.name
                with source.open("rb") as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
                    dst.flush()
                    os.fsync(dst.fileno())
                os.chmod(target, 0o600)
            if _tree_digest(temporary) != plan["scan"]["tree_sha256"]:
                raise GateBPromotionError("staged scan changed during copy")
            os.rename(temporary, scan_target)
            writes += 1
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
    if plan["review_profile"]["action"] == "CREATE":
        data = reviewed_profile.read_bytes()
        with profile_target.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(profile_target, 0o600)
        writes += 1
    verified = build_plan(
        frozen_family=frozen_family,
        staged_scan=staged_scan,
        reviewed_profile=reviewed_profile,
        approval_file=approval_file,
        parser_sha256=parser_sha256,
    )
    if verified["result"] != "NO_OP_IDENTICAL":
        raise GateBPromotionError("post-promotion verification did not converge to byte-identical state")
    return {**verified, "result": "PROMOTION_PASS", "writes_performed": writes}


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan/apply a create-once Lidl Gate B canonical scan/profile promotion")
    parser.add_argument("--frozen-family", type=Path, required=True)
    parser.add_argument("--staged-scan", type=Path, required=True)
    parser.add_argument("--review-profile", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--parser-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        fn = apply_plan if args.apply else build_plan
        result = fn(
            frozen_family=args.frozen_family,
            staged_scan=args.staged_scan,
            reviewed_profile=args.review_profile,
            approval_file=args.approval,
            parser_sha256=args.parser_sha256,
        )
    except GateBPromotionError as exc:
        print(f"ERROR: {exc}")
        return 2
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
