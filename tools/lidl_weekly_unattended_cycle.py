#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
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

from lidl_weekly_semantic_view import build_semantic_view  # noqa: E402
from lidl_weekly_shadow_controller import (  # noqa: E402
    BLOCKED_STATE,
    NO_OP_STATE,
    READY_STATE,
    WAIT_STATE,
    run_controller,
)
from lidl_weekly_trust_state import (  # noqa: E402
    RECEIPT_STRATEGY,
    STRATEGY as TRUST_STATE_STRATEGY,
    build_cycle_evidence,
    build_state,
    load_json,
    sha_file,
    write_create_only,
)


RUNNER_VERSION = "lidl-weekly-unattended-cycle-v1"
EXIT_CODES = {"COMPLETE": 0, WAIT_STATE: 20, BLOCKED_STATE: 30}


class LidlWeeklyUnattendedCycleError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LidlWeeklyUnattendedCycleError(message)


def _regular_file(path: Path, label: str) -> None:
    _require(not path.is_symlink() and path.is_file(), f"{label} must be a regular file")


def _prepare_output_root(path: Path) -> Path:
    _require(not path.is_symlink(), "output directory must not be a symlink")
    path.mkdir(parents=True, exist_ok=True)
    _require(path.is_dir(), "output path is not a directory")
    _require(not any(path.iterdir()), f"output directory must be empty: {path}")
    return path.resolve()


def _load_previous_bundle(
    previous_cycle_dir: Path | None,
) -> tuple[Path | None, dict[str, Any] | None, str | None]:
    if previous_cycle_dir is None:
        return None, None, None

    root = previous_cycle_dir
    _require(not root.is_symlink() and root.is_dir(), "previous cycle must be a directory")
    controller_path = root / "controller" / "controller-manifest.json"
    state_path = root / "trust-state.json"
    receipt_path = root / "trust-receipt.json"
    for path, label in (
        (controller_path, "previous controller manifest"),
        (state_path, "previous trust state"),
        (receipt_path, "previous trust receipt"),
    ):
        _regular_file(path, label)

    state = load_json(state_path)
    receipt = load_json(receipt_path)
    _require(
        state.get("strategy") == TRUST_STATE_STRATEGY,
        "previous trust state strategy mismatch",
    )
    _require(
        receipt.get("strategy") == RECEIPT_STRATEGY,
        "previous trust receipt strategy mismatch",
    )
    state_sha = sha_file(state_path)
    _require(
        receipt.get("state_sha256") == state_sha,
        "previous trust receipt does not bind previous state bytes",
    )
    _require(
        state.get("production_write_authorized") is False,
        "previous trust state contains production write authority",
    )
    return controller_path, state, state_sha


def _safe_component(value: Any, label: str) -> str:
    text = str(value or "")
    _require(bool(text), f"{label} is missing")
    _require(Path(text).name == text and text not in {".", ".."}, f"{label} is unsafe")
    return text


def _resolve_semantic_inputs(
    *,
    corpus: Path,
    one_shot: Mapping[str, Any],
) -> tuple[Path, Path, int]:
    _require(one_shot.get("result") == READY_STATE, "one-shot must be READY")
    match = one_shot.get("corpus_match")
    source = one_shot.get("source")
    _require(isinstance(match, Mapping), "one-shot corpus_match is missing")
    _require(isinstance(source, Mapping), "one-shot source is missing")
    readiness = source.get("readiness")
    _require(isinstance(readiness, Mapping), "one-shot source readiness is missing")

    flyer_key = _safe_component(match.get("flyer_key"), "flyer_key")
    scan = _safe_component(match.get("scan"), "scan")
    try:
        page_count = int(readiness.get("page_count"))
    except (TypeError, ValueError) as exc:
        raise LidlWeeklyUnattendedCycleError("source page_count is invalid") from exc
    _require(page_count > 0, "source page_count must be positive")

    flyers_root = (corpus.resolve() / "flyers").resolve()
    flyer_dir = flyers_root / flyer_key
    scans_root = flyer_dir / "scans"
    scan_dir = scans_root / scan
    _require(not flyer_dir.is_symlink() and flyer_dir.is_dir(), "flyer directory is missing")
    _require(not scans_root.is_symlink() and scans_root.is_dir(), "scan root is missing")
    _require(not scan_dir.is_symlink() and scan_dir.is_dir(), "scan directory is missing")
    return flyer_dir, scan_dir, page_count


def _summary(
    *,
    result: str,
    reason: str,
    controller_result: str | None,
    observation: str | None = None,
    semantic_no_op: bool = False,
    transition_recorded: bool = False,
    consecutive: int = 0,
    issue_24_ready: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runner_version": RUNNER_VERSION,
        "result": result,
        "reason": reason,
        "controller_result": controller_result,
        "observation": observation,
        "semantic_no_op": semantic_no_op,
        "transition_recorded": transition_recorded,
        "consecutive_unattended_weekly_cycle_count": consecutive,
        "issue_24_two_consecutive_unattended_weekly_cycles_ready": issue_24_ready,
        "dry_run": True,
        "corpus_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "production_publish_authorized": False,
        "deployment_authorized": False,
        "systemd_change_authorized": False,
        "bounded_retry_authorized": False,
    }


def run_unattended_cycle(
    *,
    corpus: Path,
    output_dir: Path,
    target: str,
    today: date,
    observed_at: datetime,
    trigger_event: str,
    discovery_dir: Path | None = None,
    previous_cycle_dir: Path | None = None,
) -> dict[str, Any]:
    _require(
        trigger_event in {"schedule", "workflow_dispatch"},
        "unsupported trigger event",
    )
    _require(observed_at.tzinfo is not None, "observed_at must be timezone-aware")
    root = _prepare_output_root(output_dir)
    previous_controller, previous_state, previous_state_sha = _load_previous_bundle(
        previous_cycle_dir
    )

    controller_dir = root / "controller"
    controller = run_controller(
        corpus=corpus,
        output_dir=controller_dir,
        target=target,
        today=today,
        discovery_dir=discovery_dir,
        previous_manifest_path=previous_controller,
    )
    controller_result = str(controller.get("result") or "")
    if controller_result in {WAIT_STATE, BLOCKED_STATE}:
        summary = _summary(
            result=controller_result,
            reason=str(controller.get("reason") or ""),
            controller_result=controller_result,
        )
        write_create_only(root / "cycle-summary.json", summary)
        return summary

    _require(
        controller_result in {READY_STATE, NO_OP_STATE},
        f"unsupported controller result: {controller_result}",
    )
    one_shot_path = controller_dir / "one-shot" / "one-shot-status.json"
    _regular_file(one_shot_path, "one-shot status")
    one_shot = load_json(one_shot_path)
    flyer_dir, scan_dir, page_count = _resolve_semantic_inputs(
        corpus=corpus,
        one_shot=one_shot,
    )

    semantic_dir = root / "semantic"
    build_semantic_view(
        flyer_dir=flyer_dir,
        scan_dir=scan_dir,
        output_dir=semantic_dir,
        page_count=page_count,
    )
    cycle = build_cycle_evidence(
        controller,
        one_shot,
        semantic_dir=semantic_dir,
    )
    state, receipt = build_state(
        cycle,
        observed_at=observed_at,
        trigger_event=trigger_event,
        previous=previous_state,
        previous_state_sha256=previous_state_sha,
    )

    if controller_result == NO_OP_STATE:
        _require(
            previous_state is not None,
            "controller NO_OP requires previous trust-state evidence",
        )
        _require(
            state.get("semantic_no_op") is True,
            "controller NO_OP is not an exact semantic no-op",
        )
        reason = "unchanged_source_parser_profile_and_semantic_evidence"
    else:
        _require(
            state.get("semantic_no_op") is False,
            "READY controller result cannot be semantic no-op",
        )
        reason = "completed_exact_shadow_cycle"

    state_sha = write_create_only(root / "trust-state.json", state)
    _require(
        receipt.get("state_sha256") == state_sha,
        "trust receipt does not bind current state bytes",
    )
    write_create_only(root / "trust-receipt.json", receipt)

    summary = _summary(
        result="COMPLETE",
        reason=reason,
        controller_result=controller_result,
        observation=str(state.get("observation") or ""),
        semantic_no_op=bool(state.get("semantic_no_op")),
        transition_recorded=bool(state.get("transition_recorded")),
        consecutive=int(state.get("consecutive_unattended_weekly_cycle_count") or 0),
        issue_24_ready=bool(
            state.get("issue_24_two_consecutive_unattended_weekly_cycles_ready")
        ),
    )
    write_create_only(root / "cycle-summary.json", summary)
    return summary


def _date_arg(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _datetime_arg(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("observed-at must include a timezone")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compose the read-only Lidl Gate A controller, semantic view and "
            "weekly trust-state verifier into one non-activating cycle runner."
        )
    )
    parser.add_argument("--corpus", type=Path, default=Path("/corpus"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target", choices=("current", "next"), default="current")
    parser.add_argument("--today", type=_date_arg, required=True)
    parser.add_argument("--observed-at", type=_datetime_arg, required=True)
    parser.add_argument(
        "--trigger-event",
        choices=("schedule", "workflow_dispatch"),
        required=True,
    )
    parser.add_argument("--discovery-dir", type=Path)
    parser.add_argument("--previous-cycle-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = run_unattended_cycle(
            corpus=args.corpus,
            output_dir=args.output_dir,
            target=args.target,
            today=args.today,
            observed_at=args.observed_at,
            trigger_event=args.trigger_event,
            discovery_dir=args.discovery_dir,
            previous_cycle_dir=args.previous_cycle_dir,
        )
    except Exception as exc:
        summary = _summary(
            result=BLOCKED_STATE,
            reason=f"runner_contract_error:{type(exc).__name__}:{exc}",
            controller_result=None,
        )
        try:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            if not (args.output_dir / "cycle-summary.json").exists():
                write_create_only(args.output_dir / "cycle-summary.json", summary)
        except Exception:
            pass
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return EXIT_CODES.get(str(summary["result"]), 30)


if __name__ == "__main__":
    raise SystemExit(main())
