#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping
from urllib.parse import urlsplit


PLAN_VERSION = "lidl-gate-b-freeze-plan-v2-source-revision"
EXPECTED_GATE_A_RESULT = "WAIT"
EXPECTED_GATE_A_REASON = "one_shot_wait_source"
EXPECTED_ONE_SHOT_RESULT = "WAIT_SOURCE"
EXPECTED_ONE_SHOT_REASON = "exact_source_not_archived_in_immutable_corpus"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
FLYER_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
STAGING_RE = re.compile(r"^\.gate-b-freeze-[0-9a-f]{16}\.staging$")


class LidlGateBFreezePlanError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LidlGateBFreezePlanError(message)


def _load_json(path: Path) -> dict[str, Any]:
    _require(
        path.is_file() and not path.is_symlink(),
        f"unsafe or missing JSON file: {path}",
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LidlGateBFreezePlanError(
            f"unreadable JSON file {path}: {type(exc).__name__}"
        ) from exc
    _require(isinstance(payload, dict), f"JSON root must be an object: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    _require(path.is_file() and not path.is_symlink(), f"unsafe or missing file: {path}")
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _parse_request(path: Path) -> dict[str, str]:
    _require(
        path.is_file() and not path.is_symlink(),
        f"unsafe or missing request file: {path}",
    )
    result: dict[str, str] = {}
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        _require("=" in raw, f"invalid run-request line {line_number}")
        key, value = raw.split("=", 1)
        _require(
            bool(key) and key not in result,
            f"duplicate or empty run-request key: {key!r}",
        )
        result[key] = value
    return result


def _safe_dir(path: Path, *, label: str) -> Path:
    _require(path.is_dir() and not path.is_symlink(), f"{label} is missing or unsafe: {path}")
    resolved = path.resolve()
    _require(resolved == path.absolute(), f"{label} path drift: {path}")
    return resolved


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _stable_source_identity(source_json: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(source_json)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LidlGateBFreezePlanError(
            f"source JSON is invalid: {type(exc).__name__}"
        ) from exc
    _require(isinstance(payload, Mapping), "source JSON root must be an object")
    flyer = payload.get("flyer")
    _require(isinstance(flyer, Mapping), "source JSON flyer object is missing")

    viewer_url = str(flyer.get("flyerUrlAbsolute") or "")
    document_url = str(flyer.get("hiResPdfUrl") or flyer.get("pdfUrl") or "")
    pages = flyer.get("pages") or []
    _require(isinstance(pages, list), "source JSON pages must be a list")
    regions = sorted(
        str(row.get("code"))
        for row in (flyer.get("regions") or [])
        if isinstance(row, Mapping) and row.get("code") is not None
    )
    identity = {
        "official_flyer_id": str(flyer.get("id") or ""),
        "viewer_path": urlsplit(viewer_url).path,
        "document_path": urlsplit(document_url).path,
        "valid_from": str(flyer.get("offerStartDate") or ""),
        "valid_until": str(flyer.get("offerEndDate") or ""),
        "advertised_regions": regions,
        "page_count": len(pages),
    }
    for key in (
        "official_flyer_id",
        "viewer_path",
        "document_path",
        "valid_from",
        "valid_until",
    ):
        _require(bool(identity[key]), f"stable source identity field is missing: {key}")
    return identity


def _logical_source_identity(stable_identity: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in stable_identity.items()
        if key != "document_path"
    }


def _expect_flags(
    payload: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    label: str,
) -> None:
    for key, value in expected.items():
        _require(payload.get(key) is value, f"{label} safety mismatch: {key}")


def _validate_sha(value: Any, *, label: str) -> str:
    text = str(value or "")
    _require(bool(SHA256_RE.fullmatch(text)), f"{label} is not SHA256")
    return text


def _validate_date(value: Any, *, label: str) -> str:
    text = str(value or "")
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise LidlGateBFreezePlanError(f"{label} is not a canonical date") from exc
    _require(parsed.isoformat() == text, f"{label} is not a canonical date")
    return text


def _validate_active_private_staging(
    staging: Path,
    *,
    source_pdf_sha256: str,
    stable_identity: Mapping[str, Any],
) -> None:
    _require(bool(STAGING_RE.fullmatch(staging.name)), "active private staging name is invalid")
    _require(staging.is_dir() and not staging.is_symlink(), "active private staging is missing or unsafe")
    metadata = staging.stat(follow_symlinks=False)
    _require(metadata.st_uid == os.geteuid(), "active private staging owner UID mismatch")
    _require(metadata.st_gid == os.getegid(), "active private staging owner GID mismatch")
    _require(stat.S_IMODE(metadata.st_mode) == 0o700, "active private staging mode mismatch")

    expected_names = {"source.pdf", "source.json", "discovery-meta.json"}
    actual_names = {path.name for path in staging.iterdir()}
    _require(actual_names == expected_names, "active private staging file set mismatch")
    for name in sorted(expected_names):
        path = staging / name
        _require(path.is_file() and not path.is_symlink(), f"active private staging file is unsafe: {name}")
        file_meta = path.stat(follow_symlinks=False)
        _require(file_meta.st_uid == os.geteuid(), f"active private staging file owner UID mismatch: {name}")
        _require(file_meta.st_gid == os.getegid(), f"active private staging file owner GID mismatch: {name}")
        _require(stat.S_IMODE(file_meta.st_mode) == 0o600, f"active private staging file mode mismatch: {name}")

    _require(
        _sha256_file(staging / "source.pdf") == source_pdf_sha256,
        "active private staging PDF SHA mismatch",
    )
    _require(
        _stable_source_identity((staging / "source.json").read_bytes())
        == dict(stable_identity),
        "active private staging stable identity mismatch",
    )


def _corpus_identity_conflicts(
    flyers_root: Path,
    *,
    source_pdf_sha256: str,
    stable_identity: Mapping[str, Any],
    active_private_staging: Path | None = None,
) -> None:
    for flyer_dir in sorted(flyers_root.iterdir()):
        _require(not flyer_dir.is_symlink(), f"corpus child is a symlink: {flyer_dir}")
        if active_private_staging is not None and flyer_dir == active_private_staging:
            _validate_active_private_staging(
                flyer_dir,
                source_pdf_sha256=source_pdf_sha256,
                stable_identity=stable_identity,
            )
            continue
        if not flyer_dir.is_dir():
            continue
        pdf = flyer_dir / "source.pdf"
        raw = flyer_dir / "source.json"
        if pdf.exists():
            _require(pdf.is_file() and not pdf.is_symlink(), f"unsafe corpus PDF: {pdf}")
            if _sha256_file(pdf) == source_pdf_sha256:
                raise LidlGateBFreezePlanError(
                    f"exact source PDF is already frozen in corpus: {flyer_dir.name}"
                )
        if raw.exists():
            _require(raw.is_file() and not raw.is_symlink(), f"unsafe corpus JSON: {raw}")
            existing_identity = _stable_source_identity(raw.read_bytes())
            if existing_identity == dict(stable_identity):
                raise LidlGateBFreezePlanError(
                    f"stable source identity is already frozen in corpus: {flyer_dir.name}"
                )


def _resolve_destination(
    flyers_root: Path,
    *,
    flyer_key: str,
    source_pdf_sha256: str,
    stable_identity: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    base = flyers_root / flyer_key
    _require(not base.is_symlink(), "base flyer destination is a symlink")
    if not base.exists():
        return base, {
            "strategy": "base_flyer_key",
            "base_flyer_key": flyer_key,
            "revision_of": None,
        }

    _require(base.is_dir(), "occupied base flyer destination is not a directory")
    base_pdf = base / "source.pdf"
    base_raw = base / "source.json"
    _require(
        base_pdf.is_file() and not base_pdf.is_symlink(),
        "occupied base flyer source PDF is missing or unsafe",
    )
    _require(
        base_raw.is_file() and not base_raw.is_symlink(),
        "occupied base flyer source JSON is missing or unsafe",
    )
    base_identity = _stable_source_identity(base_raw.read_bytes())
    _require(
        _logical_source_identity(base_identity)
        == _logical_source_identity(stable_identity),
        "occupied base flyer key represents a different logical flyer",
    )
    _require(
        base_identity["document_path"] != stable_identity["document_path"],
        "occupied base flyer key has the same document path",
    )

    revision_key = f"{flyer_key}--src-{source_pdf_sha256[:12]}"
    _require(
        bool(FLYER_KEY_RE.fullmatch(revision_key))
        and revision_key not in {".", ".."},
        "derived source revision flyer key is unsafe or too long",
    )
    destination = flyers_root / revision_key
    _require(
        not destination.exists() and not destination.is_symlink(),
        "planned source revision destination already exists",
    )
    return destination, {
        "strategy": "content_addressed_source_revision",
        "base_flyer_key": flyer_key,
        "revision_of": flyer_key,
        "base_document_path": base_identity["document_path"],
        "live_document_path": stable_identity["document_path"],
        "base_pdf_sha256": _sha256_file(base_pdf),
    }


def build_freeze_plan(
    *,
    gate_a_run_dir: Path,
    evidence_root: Path,
    corpus_root: Path,
) -> dict[str, Any]:
    evidence_root = _safe_dir(evidence_root, label="Gate A evidence root")
    corpus_root = _safe_dir(corpus_root, label="authoritative corpus root")
    flyers_root = _safe_dir(corpus_root / "flyers", label="authoritative flyers root")

    _require(
        not gate_a_run_dir.is_symlink(),
        f"Gate A run directory is a symlink: {gate_a_run_dir}",
    )
    run_dir = gate_a_run_dir.resolve()
    _require(run_dir.is_dir(), f"Gate A run directory is missing: {run_dir}")
    _require(_is_within(run_dir, evidence_root), "Gate A run directory is outside evidence root")
    _require(
        run_dir.parent == evidence_root,
        "Gate A run directory must be a direct evidence-root child",
    )
    _require(run_dir.name.startswith("lidl-gate-a-"), "Gate A run directory name is invalid")

    request = _parse_request(run_dir / "run-request.txt")
    controller = _load_json(run_dir / "controller" / "controller-manifest.json")
    one_shot_root = run_dir / "controller" / "one-shot"
    one_shot = _load_json(one_shot_root / "one-shot-status.json")

    for key, value in {
        "production_database_write": "false",
        "review_write": "false",
        "production_publish": "false",
        "production_deploy": "false",
        "systemd_change": "false",
        "use_previous": "false",
        "previous_manifest": "none",
    }.items():
        _require(request.get(key) == value, f"run-request mismatch: {key}")
    _require(request.get("corpus_root") == str(corpus_root), "run-request corpus root mismatch")
    registered_commit = str(request.get("registered_commit") or "")
    registered_image_id = str(request.get("registered_image_id") or "")
    _require(bool(COMMIT_RE.fullmatch(registered_commit)), "registered commit is invalid")
    _require(bool(IMAGE_RE.fullmatch(registered_image_id)), "registered image ID is invalid")
    target = str(request.get("target") or "")
    _require(target in {"current", "next"}, "run-request target is invalid")
    as_of = _validate_date(request.get("as_of"), label="run-request as_of")

    _expect_flags(
        controller,
        {
            "dry_run": True,
            "corpus_write_authorized": False,
            "database_write_authorized": False,
            "review_write_authorized": False,
            "production_publish_authorized": False,
            "systemd_change_authorized": False,
            "bounded_retry_authorized": False,
            "new_immutable_snapshot_required": False,
            "shadow_execution_required": False,
        },
        label="controller",
    )
    _require(controller.get("result") == EXPECTED_GATE_A_RESULT, "Gate A result is not WAIT")
    _require(controller.get("reason") == EXPECTED_GATE_A_REASON, "Gate A reason mismatch")
    _require(
        controller.get("one_shot_result") == EXPECTED_ONE_SHOT_RESULT,
        "Gate A one-shot result mismatch",
    )
    _require(
        controller.get("one_shot_reason") == EXPECTED_ONE_SHOT_REASON,
        "Gate A one-shot reason mismatch",
    )
    _require(controller.get("execution_fingerprint") is None, "WAIT result unexpectedly has a fingerprint")
    _require(controller.get("target") == target, "controller target mismatch")
    _require(controller.get("today_berlin") == as_of, "controller Berlin date mismatch")

    _expect_flags(
        one_shot,
        {
            "dry_run": True,
            "corpus_write": False,
            "db_write": False,
            "review_seed": False,
            "auto_approve": False,
            "auto_publish": False,
            "systemd_change": False,
        },
        label="one-shot",
    )
    _require(one_shot.get("result") == EXPECTED_ONE_SHOT_RESULT, "one-shot result mismatch")
    _require(one_shot.get("reason") == EXPECTED_ONE_SHOT_REASON, "one-shot reason mismatch")
    _require(one_shot.get("target") == target, "one-shot target mismatch")
    _require(one_shot.get("today_berlin") == as_of, "one-shot Berlin date mismatch")
    _require(one_shot.get("corpus_match") is None, "WAIT_SOURCE unexpectedly has a corpus match")

    source = one_shot.get("source")
    _require(isinstance(source, Mapping), "one-shot source metadata is missing")
    readiness = source.get("readiness")
    _require(isinstance(readiness, Mapping), "source readiness metadata is missing")
    _require(readiness.get("state") == "SOURCE_AVAILABLE", "source is not ready for freezing")
    source_pdf_sha256 = _validate_sha(source.get("pdf_sha256"), label="one-shot PDF SHA")
    source_raw_sha256 = _validate_sha(source.get("raw_sha256"), label="one-shot raw SHA")
    valid_from = _validate_date(source.get("valid_from"), label="source valid_from")
    valid_until = _validate_date(source.get("valid_until"), label="source valid_until")
    _require(valid_from <= valid_until, "source validity window is reversed")

    discovery_root = one_shot_root / "discovery"
    _safe_dir(discovery_root, label="Gate A discovery root")
    discovery = _load_json(discovery_root / "discovery.json")
    _require(discovery.get("today_berlin") == as_of, "discovery Berlin date mismatch")
    family_root = _safe_dir(
        discovery_root / f"family-{target}",
        label="selected discovery family",
    )
    meta = _load_json(family_root / "meta.json")
    source_pdf = family_root / "source.pdf"
    source_json = family_root / "source.json"
    actual_pdf_sha256 = _sha256_file(source_pdf)
    actual_raw_sha256 = _sha256_file(source_json)

    _require(actual_pdf_sha256 == source_pdf_sha256, "source PDF SHA mismatch against one-shot status")
    _require(actual_raw_sha256 == source_raw_sha256, "source JSON SHA mismatch against one-shot status")
    _require(meta.get("target") == target, "discovery meta target mismatch")
    _require(meta.get("pdf_sha256") == actual_pdf_sha256, "discovery meta PDF SHA mismatch")
    _require(meta.get("raw_sha256") == actual_raw_sha256, "discovery meta raw SHA mismatch")
    _require(int(meta.get("pdf_bytes") or -1) == source_pdf.stat().st_size, "discovery meta PDF byte count mismatch")
    _require(int(meta.get("raw_bytes") or -1) == source_json.stat().st_size, "discovery meta raw byte count mismatch")
    _require(meta.get("valid_from") == valid_from, "discovery meta valid_from mismatch")
    _require(meta.get("valid_until") == valid_until, "discovery meta valid_until mismatch")
    _require(
        str(meta.get("route_region") or "") == str(source.get("route_region") or ""),
        "route region mismatch",
    )

    flyer_key = str(meta.get("flyer_identifier") or "")
    _require(bool(FLYER_KEY_RE.fullmatch(flyer_key)), "flyer identifier is unsafe")
    _require(flyer_key not in {".", ".."}, "flyer identifier is unsafe")

    stable_identity = _stable_source_identity(source_json.read_bytes())
    stable_identity_sha256 = _canonical_digest(stable_identity)
    _require(
        str(meta.get("official_flyer_id") or "") == stable_identity["official_flyer_id"],
        "official flyer ID mismatch",
    )
    _require(meta.get("valid_from") == stable_identity["valid_from"], "stable identity valid_from mismatch")
    _require(meta.get("valid_until") == stable_identity["valid_until"], "stable identity valid_until mismatch")
    _require(int(meta.get("page_count") or -1) == stable_identity["page_count"], "stable identity page count mismatch")
    advertised_regions = sorted(str(value) for value in (meta.get("advertised_regions") or []))
    _require(
        advertised_regions == stable_identity["advertised_regions"],
        "advertised region identity mismatch",
    )

    destination, destination_identity = _resolve_destination(
        flyers_root,
        flyer_key=flyer_key,
        source_pdf_sha256=actual_pdf_sha256,
        stable_identity=stable_identity,
    )

    files = [
        {
            "name": "source.pdf",
            "source": str(source_pdf),
            "destination": str(destination / "source.pdf"),
            "bytes": source_pdf.stat().st_size,
            "sha256": actual_pdf_sha256,
        },
        {
            "name": "source.json",
            "source": str(source_json),
            "destination": str(destination / "source.json"),
            "bytes": source_json.stat().st_size,
            "sha256": actual_raw_sha256,
        },
        {
            "name": "meta.json",
            "source": str(family_root / "meta.json"),
            "destination": str(destination / "discovery-meta.json"),
            "bytes": (family_root / "meta.json").stat().st_size,
            "sha256": _sha256_file(family_root / "meta.json"),
        },
    ]
    plan_identity = {
        "registered_commit": registered_commit,
        "registered_image_id": registered_image_id,
        "target": target,
        "as_of": as_of,
        "flyer_key": flyer_key,
        "source_pdf_sha256": actual_pdf_sha256,
        "source_raw_sha256": actual_raw_sha256,
        "stable_source_identity_sha256": stable_identity_sha256,
        "destination": str(destination),
        "destination_strategy": destination_identity["strategy"],
    }
    plan_fingerprint = _canonical_digest(plan_identity)
    active_private_staging = (
        flyers_root / f".gate-b-freeze-{plan_fingerprint[:16]}.staging"
    )
    _corpus_identity_conflicts(
        flyers_root,
        source_pdf_sha256=actual_pdf_sha256,
        stable_identity=stable_identity,
        active_private_staging=active_private_staging,
    )

    return {
        "schema_version": 1,
        "plan_version": PLAN_VERSION,
        "result": "READY_TO_FREEZE",
        "reason": "validated_gate_a_wait_source_evidence",
        "plan_fingerprint": plan_fingerprint,
        "gate_a": {
            "run_dir": str(run_dir),
            "registered_commit": registered_commit,
            "registered_image_id": registered_image_id,
            "target": target,
            "as_of": as_of,
            "result": EXPECTED_GATE_A_RESULT,
            "reason": EXPECTED_GATE_A_REASON,
            "one_shot_result": EXPECTED_ONE_SHOT_RESULT,
            "one_shot_reason": EXPECTED_ONE_SHOT_REASON,
        },
        "source": {
            "flyer_key": flyer_key,
            "route_region": str(meta.get("route_region") or ""),
            "valid_from": valid_from,
            "valid_until": valid_until,
            "official_flyer_id": stable_identity["official_flyer_id"],
            "page_count": stable_identity["page_count"],
            "pdf_sha256": actual_pdf_sha256,
            "raw_sha256": actual_raw_sha256,
            "stable_source_identity": stable_identity,
            "stable_source_identity_sha256": stable_identity_sha256,
        },
        "destination": {
            "flyer_dir": str(destination),
            "must_not_exist": True,
            **destination_identity,
            "files": files,
        },
        "apply_contract": {
            "mode": "exclusive_create_only",
            "required_owner": "andris:andris",
            "directory_mode": "0700",
            "file_mode": "0600",
            "post_copy_sha256_verification_required": True,
            "rollback_before_commit": "remove_private_staging_only",
            "separate_owner_authorization_required": True,
        },
        "safety": {
            "plan_only": True,
            "corpus_write_authorized": False,
            "database_write_authorized": False,
            "review_write_authorized": False,
            "production_publish_authorized": False,
            "production_deploy_authorized": False,
            "systemd_change_authorized": False,
            "bounded_retry_authorized": False,
        },
    }


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _require(not path.exists(), f"output already exists: {path}")
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a deterministic, read-only Gate B freeze plan from one "
            "completed Gate A WAIT_SOURCE evidence directory. This tool never "
            "writes to the immutable corpus."
        )
    )
    parser.add_argument("--gate-a-run-dir", type=Path, required=True)
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path("/home/andris/hermes-deals-lidl-gate-a-evidence"),
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=Path("/home/andris/hermes-deals-lidl-corpus"),
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = build_freeze_plan(
            gate_a_run_dir=args.gate_a_run_dir,
            evidence_root=args.evidence_root,
            corpus_root=args.corpus_root,
        )
        _atomic_json(args.output, plan)
    except LidlGateBFreezePlanError as exc:
        print(f"BLOCKED: {exc}")
        return 30
    print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
    print("RESULT=READY_TO_FREEZE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
