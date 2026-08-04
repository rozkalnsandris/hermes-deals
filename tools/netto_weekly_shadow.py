#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from netto_shadow_promotion import (  # noqa: E402
    AUDITED_FIELDS,
    DEFAULT_COVERAGE_THRESHOLDS,
    DEFAULT_MINIMUM_SAMPLES,
    DEFAULT_PRECISION_THRESHOLDS,
    FAMILY_PRIMARY_SCOPE,
    FAMILY_PRIMARY_STORE_ID,
    AuditRow,
    Classification,
    EvidenceBinding,
    EvidenceStatus,
    FieldMetrics,
    build_shadow_candidate,
    evaluate_corpus,
    resolve_field_evidence,
    values_equal,
    _mapping,
)
from netto_shadow_weekly import (  # noqa: E402
    MAX_RETRIES,
    WeeklyAction,
    WeeklyDecision,
    WeeklyInput,
    build_write_plan,
    decide_weekly_action,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path | None, value: Any) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(text, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Netto review gates and weekly shadow controller"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit")
    audit.add_argument("--input", type=Path, required=True)
    audit.add_argument("--output", type=Path)
    audit.add_argument("--minimum-samples", type=int, default=DEFAULT_MINIMUM_SAMPLES)

    decide = subparsers.add_parser("decide")
    decide.add_argument("--input", type=Path, required=True)
    decide.add_argument("--output", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "audit":
            payload = _load_json(args.input)
            if not isinstance(payload, list):
                raise ValueError("audit input must be a JSON array")
            result = evaluate_corpus(payload, minimum_samples=args.minimum_samples)
            _write_json(args.output, result)
            return 0
        if args.command == "decide":
            result = decide_weekly_action(_mapping(_load_json(args.input), "input"))
            _write_json(args.output, asdict(result))
            return 2 if result.severity == "error" else 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR|{exc}", flush=True)
        return 2
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
