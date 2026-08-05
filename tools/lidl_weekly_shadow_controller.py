#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPO_ROOT / "tools"
BACKEND_ROOT = REPO_ROOT / "backend"
for candidate in (TOOLS_ROOT, BACKEND_ROOT):
    text = str(candidate)
    if text not in sys.path:
        sys.path.insert(0, text)

from lidl_weekly_one_shot import (  # noqa: E402
    StoreBinding,
    berlin_today,
    run_one_shot,
)


CONTROLLER_VERSION = "lidl-weekly-shadow-controller-v1"
READY_STATE = "READY"
NO_OP_STATE = "NO_OP"
WAIT_STATE = "WAIT"
BLOCKED_STATE = "BLOCKED"
EXIT_CODES = {
    READY_STATE: 0,
    NO_OP_STATE: 0,
    WAIT_STATE: 20,
    BLOCKED_STATE: 30,
}
WAIT_RESULTS = frozenset({"WAIT_SOURCE", "WAIT_SCAN", "WAIT_PROFILE"})
BLOCKED_RESULTS = frozenset({"BLOCKED_SOURCE_DRIFT", "BLOCKED_PARSER_DRIFT"})
SAFETY_FLAGS = (
    "dry_run",
    "corpus_write",
    "db_write",
    "review_seed",
    "auto_approve",
    "auto_publish",
    "systemd_change",
)


class LidlWeeklyShadowControllerError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LidlWeeklyShadowControllerError(message)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _validate_one_shot_safety(status: Mapping[str, Any]) -> None:
    expected = {
        "dry_run": True,
        "corpus_write": False,
        "db_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "systemd_change": False,
    }
    for key, value in expected.items():
        _require(
            status.get(key) is value,
            f"one-shot safety flag mismatch: {key}",
        )


def _ready_fingerprint(status: Mapping[str, Any]) -> str:
    corpus_match = status.get("corpus_match")
    review_profile = status.get("review_profile")
    _require(isinstance(corpus_match, Mapping), "READY corpus_match is missing")
    _require(isinstance(review_profile, Mapping), "READY review_profile is missing")

    identity = {
        "target": str(status.get("target") or ""),
        "flyer_key": str(corpus_match.get("flyer_key") or ""),
        "scan": str(corpus_match.get("scan") or ""),
        "source_pdf_sha256": str(corpus_match.get("source_pdf_sha256") or ""),
        "stable_source_identity_sha256": str(
            corpus_match.get("stable_source_identity_sha256") or ""
        ),
        "parser_version": str(status.get("parser_version") or ""),
        "parser_sha256": str(status.get("parser_sha256") or ""),
        "review_profile": dict(review_profile),
    }
    for key in (
        "target",
        "flyer_key",
        "scan",
        "source_pdf_sha256",
        "stable_source_identity_sha256",
        "parser_version",
        "parser_sha256",
    ):
        _require(bool(identity[key]), f"READY fingerprint field is missing: {key}")
    for key in ("source_pdf_sha256", "stable_source_identity_sha256", "parser_sha256"):
        value = str(identity[key])
        _require(
            len(value) == 64 and all(character in "0123456789abcdef" for character in value),
            f"READY fingerprint field is not SHA256: {key}",
        )
    return _canonical_digest(identity)


def load_previous_manifest(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LidlWeeklyShadowControllerError(
            f"previous manifest is unreadable: {type(exc).__name__}"
        ) from exc
    _require(isinstance(payload, dict), "previous manifest must be an object")
    _require(payload.get("schema_version") == 1, "previous manifest schema mismatch")
    _require(
        payload.get("controller_version") == CONTROLLER_VERSION,
        "previous manifest controller version mismatch",
    )
    _require(
        payload.get("result") in {READY_STATE, NO_OP_STATE},
        "previous manifest is not a completed shadow decision",
    )
    fingerprint = str(payload.get("execution_fingerprint") or "")
    _require(
        len(fingerprint) == 64
        and all(character in "0123456789abcdef" for character in fingerprint),
        "previous manifest fingerprint is invalid",
    )
    expected = {
        "dry_run": True,
        "corpus_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "production_publish_authorized": False,
        "systemd_change_authorized": False,
    }
    for key, value in expected.items():
        _require(payload.get(key) is value, f"previous manifest safety mismatch: {key}")
    return payload


def evaluate_one_shot_status(
    status: Mapping[str, Any],
    *,
    previous_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _require(isinstance(status, Mapping), "one-shot status must be an object")
    _validate_one_shot_safety(status)
    one_shot_result = str(status.get("result") or "")
    _require(one_shot_result, "one-shot result is missing")

    fingerprint: str | None = None
    previous_fingerprint: str | None = None
    unchanged = False
    new_snapshot_required = False
    shadow_execution_required = False

    if one_shot_result == READY_STATE:
        fingerprint = _ready_fingerprint(status)
        if previous_manifest is not None:
            previous_fingerprint = str(
                previous_manifest.get("execution_fingerprint") or ""
            )
            unchanged = previous_fingerprint == fingerprint
        if unchanged:
            result = NO_OP_STATE
            reason = "unchanged_exact_shadow_input"
        else:
            result = READY_STATE
            reason = "new_exact_shadow_input"
            new_snapshot_required = True
            shadow_execution_required = True
    elif one_shot_result in WAIT_RESULTS:
        result = WAIT_STATE
        reason = f"one_shot_{one_shot_result.lower()}"
    elif one_shot_result in BLOCKED_RESULTS:
        result = BLOCKED_STATE
        reason = f"one_shot_{one_shot_result.lower()}"
    else:
        raise LidlWeeklyShadowControllerError(
            f"unsupported one-shot result: {one_shot_result}"
        )

    return {
        "schema_version": 1,
        "controller_version": CONTROLLER_VERSION,
        "result": result,
        "reason": reason,
        "one_shot_result": one_shot_result,
        "one_shot_reason": str(status.get("reason") or ""),
        "target": str(status.get("target") or ""),
        "today_berlin": str(status.get("today_berlin") or ""),
        "execution_fingerprint": fingerprint,
        "previous_execution_fingerprint": previous_fingerprint,
        "unchanged_exact_input": unchanged,
        "new_immutable_snapshot_required": new_snapshot_required,
        "shadow_execution_required": shadow_execution_required,
        "dry_run": True,
        "corpus_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "production_publish_authorized": False,
        "systemd_change_authorized": False,
        "bounded_retry_authorized": False,
    }


def run_controller(
    *,
    corpus: Path,
    output_dir: Path,
    target: str,
    today: date,
    discovery_dir: Path | None = None,
    previous_manifest_path: Path | None = None,
) -> dict[str, Any]:
    root = output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise LidlWeeklyShadowControllerError(
            f"output directory must be empty: {root}"
        )

    previous = load_previous_manifest(previous_manifest_path)
    one_shot_status = run_one_shot(
        corpus=corpus,
        output_dir=root / "one-shot",
        target=target,
        today=today,
        binding=StoreBinding(),
        discovery_dir=discovery_dir,
    )
    manifest = evaluate_one_shot_status(
        one_shot_status,
        previous_manifest=previous,
    )
    _atomic_json(root / "controller-manifest.json", manifest)
    return manifest


def _date_arg(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Lidl weekly Gate A shadow controller. It composes the "
            "existing one-shot readiness gate and classifies READY, NO_OP, "
            "WAIT or BLOCKED without corpus, database, Review, production or "
            "systemd writes."
        )
    )
    parser.add_argument("--corpus", type=Path, default=Path("/corpus"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target", choices=("current", "next"), default="next")
    parser.add_argument("--today", type=_date_arg, default=berlin_today())
    parser.add_argument("--discovery-dir", type=Path)
    parser.add_argument("--previous-manifest", type=Path)
    return parser


def _blocked_manifest(args: argparse.Namespace, exc: Exception) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "controller_version": CONTROLLER_VERSION,
        "result": BLOCKED_STATE,
        "reason": f"controller_contract_error:{type(exc).__name__}:{exc}",
        "one_shot_result": None,
        "one_shot_reason": None,
        "target": args.target,
        "today_berlin": args.today.isoformat(),
        "execution_fingerprint": None,
        "previous_execution_fingerprint": None,
        "unchanged_exact_input": False,
        "new_immutable_snapshot_required": False,
        "shadow_execution_required": False,
        "dry_run": True,
        "corpus_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "production_publish_authorized": False,
        "systemd_change_authorized": False,
        "bounded_retry_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = run_controller(
            corpus=args.corpus,
            output_dir=args.output_dir,
            target=args.target,
            today=args.today,
            discovery_dir=args.discovery_dir,
            previous_manifest_path=args.previous_manifest,
        )
    except Exception as exc:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        manifest = _blocked_manifest(args, exc)
        _atomic_json(args.output_dir / "controller-manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    print(f"RESULT={manifest['result']}")
    return EXIT_CODES[str(manifest["result"])]


if __name__ == "__main__":
    raise SystemExit(main())
