from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping


EXPECTED_N10_LEDGER_SHA256 = (
    "bf35bff323d76a2b29a7248df067641e5b9f2a7d29329cf53bf9fc0ae832734a"
)
EXPECTED_N9_FIXTURE_MANIFEST_SHA256 = (
    "2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147"
)
EXPECTED_LEDGER_SIZE = 104385
EXPECTED_CAMPAIGN_COUNTS = {"hz31_hasb_4": 26, "hz32_hasb": 74}
BUILDER_START_MARKER = b'cat > "$SHADOW/$LEDGER_REL" <<\'JSON_LEDGER\''
BUILDER_END_MARKER = b"JSON_LEDGER"


class N10ImportError(ValueError):
    pass


def _load_reconciliation_module():
    path = Path(__file__).resolve().with_name("netto_visual_review_reconciliation.py")
    spec = importlib.util.spec_from_file_location(
        "netto_visual_review_reconciliation",
        path,
    )
    if spec is None or spec.loader is None:
        raise N10ImportError("Netto reconciliation module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RECONCILIATION = _load_reconciliation_module()


def _read_regular_bytes(path: Path, label: str) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise N10ImportError(f"{label} must be a regular file")
        return path.read_bytes()
    except N10ImportError:
        raise
    except OSError as exc:
        raise N10ImportError(f"unable to read {label}") from exc


def extract_ledger_from_builder_bytes(source: bytes) -> bytes:
    lines = source.splitlines(keepends=True)
    starts = [
        index
        for index, line in enumerate(lines)
        if line.rstrip(b"\r\n") == BUILDER_START_MARKER
    ]
    if len(starts) != 1:
        raise N10ImportError("builder must contain exactly one N10 ledger heredoc")

    start = starts[0]
    ends = [
        index
        for index in range(start + 1, len(lines))
        if lines[index].rstrip(b"\r\n") == BUILDER_END_MARKER
    ]
    if len(ends) != 1:
        raise N10ImportError("builder must contain exactly one N10 ledger terminator")

    ledger = b"".join(lines[start + 1 : ends[0]])
    if not ledger or not ledger.endswith(b"\n"):
        raise N10ImportError("builder ledger heredoc must end with a newline")
    return ledger


def load_source_ledger_bytes(
    *,
    ledger_path: Path | None = None,
    builder_script_path: Path | None = None,
) -> bytes:
    if (ledger_path is None) == (builder_script_path is None):
        raise N10ImportError(
            "provide exactly one of ledger_path or builder_script_path"
        )
    if ledger_path is not None:
        return _read_regular_bytes(ledger_path, "N10 ledger")
    assert builder_script_path is not None
    source = _read_regular_bytes(builder_script_path, "N10 builder script")
    return extract_ledger_from_builder_bytes(source)


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise N10ImportError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise N10ImportError(f"{label} root must be an object")
    return payload


def _require_false(payload: Mapping[str, Any], key: str, label: str) -> None:
    if payload.get(key) is not False:
        raise N10ImportError(f"{label}.{key} must be false")


def validate_n10_ledger(
    raw: bytes,
    *,
    expected_sha256: str = EXPECTED_N10_LEDGER_SHA256,
    expected_size: int | None = EXPECTED_LEDGER_SIZE,
) -> dict[str, Any]:
    digest = sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise N10ImportError(
            "N10 ledger SHA256 mismatch: "
            f"expected={expected_sha256} actual={digest}"
        )
    if expected_size is not None and len(raw) != expected_size:
        raise N10ImportError(
            "N10 ledger size mismatch: "
            f"expected={expected_size} actual={len(raw)}"
        )

    payload = _json_object(raw, "N10 ledger")
    expected_counts = {
        "reviewed_page_count": 17,
        "reviewed_cell_count": 100,
        "target_or_review_cell_count": 98,
        "scope_control_count": 2,
    }
    for key, expected in expected_counts.items():
        if payload.get(key) != expected:
            raise N10ImportError(f"N10 ledger {key} must equal {expected}")
    if (
        payload.get("source_n9_fixture_manifest_sha256")
        != EXPECTED_N9_FIXTURE_MANIFEST_SHA256
    ):
        raise N10ImportError("N10 ledger fixture manifest SHA256 mismatch")
    for key in (
        "automatic_approval",
        "automatic_publish",
        "production_write_performed",
    ):
        _require_false(payload, key, "N10 ledger")

    rows = payload.get("cell_reviews")
    if not isinstance(rows, list) or len(rows) != 100:
        raise N10ImportError("N10 ledger must contain exactly 100 cell reviews")

    cell_ids: set[str] = set()
    visual_indexes: set[int] = set()
    campaign_counts = {key: 0 for key in EXPECTED_CAMPAIGN_COUNTS}
    for row in rows:
        if not isinstance(row, dict):
            raise N10ImportError("N10 ledger cell reviews must be objects")
        cell_id = row.get("cell_id")
        if not isinstance(cell_id, str) or not cell_id or cell_id in cell_ids:
            raise N10ImportError("N10 ledger cell IDs must be non-empty and unique")
        cell_ids.add(cell_id)

        visual_index = row.get("visual_index")
        if not isinstance(visual_index, int) or visual_index in visual_indexes:
            raise N10ImportError("N10 ledger visual indexes must be unique integers")
        visual_indexes.add(visual_index)

        campaign = row.get("publication_slug")
        if campaign not in EXPECTED_CAMPAIGN_COUNTS:
            raise N10ImportError("N10 ledger campaign binding is invalid")
        campaign_counts[campaign] += 1

        _require_false(row, "automatic_approval_allowed", f"cell {cell_id}")
        _require_false(row, "automatic_publish_allowed", f"cell {cell_id}")

    if visual_indexes != set(range(1, 101)):
        raise N10ImportError("N10 ledger visual indexes must cover 1..100")
    if campaign_counts != EXPECTED_CAMPAIGN_COUNTS:
        raise N10ImportError("N10 ledger campaign counts do not match 26/74")
    return payload


def _encoded_json(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _destination_state(path: Path, expected: bytes, label: str) -> str:
    if path.is_symlink():
        raise N10ImportError(f"{label} destination must not be a symlink")
    if not path.exists():
        return "create"
    if not path.is_file():
        raise N10ImportError(f"{label} destination must be a regular file")
    try:
        current = path.read_bytes()
    except OSError as exc:
        raise N10ImportError(f"unable to read existing {label} destination") from exc
    if current != expected:
        raise N10ImportError(f"existing {label} destination differs")
    return "unchanged"


def _write_new_or_exact(path: Path, payload: bytes, label: str) -> str:
    state = _destination_state(path, payload, label)
    if state == "unchanged":
        return state

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.chmod(temporary, 0o644)
        try:
            os.link(temporary, path)
        except FileExistsError:
            return _destination_state(path, payload, label)
        return "created"
    except OSError as exc:
        raise N10ImportError(f"unable to write {label} destination") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def import_and_reconcile(
    *,
    first_review_path: Path,
    import_destination: Path,
    report_destination: Path,
    ledger_path: Path | None = None,
    builder_script_path: Path | None = None,
    expected_ledger_sha256: str = EXPECTED_N10_LEDGER_SHA256,
    expected_ledger_size: int | None = EXPECTED_LEDGER_SIZE,
) -> dict[str, Any]:
    raw = load_source_ledger_bytes(
        ledger_path=ledger_path,
        builder_script_path=builder_script_path,
    )
    ledger = validate_n10_ledger(
        raw,
        expected_sha256=expected_ledger_sha256,
        expected_size=expected_ledger_size,
    )
    first_review = RECONCILIATION.load_json(first_review_path)
    reconciliation = RECONCILIATION.reconcile_reviews(first_review, ledger)
    if reconciliation.get("promotion_ready") is not False:
        raise N10ImportError("reconciliation must remain fail-closed")

    report = {
        "schema_version": 1,
        "strategy": "netto_n10_import_and_reconcile_v1",
        "imported_ledger_sha256": sha256(raw).hexdigest(),
        "imported_ledger_size": len(raw),
        "source_n9_fixture_manifest_sha256": (
            EXPECTED_N9_FIXTURE_MANIFEST_SHA256
        ),
        "reconciliation": reconciliation,
        "safety": {
            "automatic_approval_enabled": False,
            "automatic_publish_enabled": False,
            "database_write_performed": False,
            "deployment_performed": False,
            "parser_activation_performed": False,
            "production_apply_authorized": False,
        },
    }
    report_bytes = _encoded_json(report)

    import_state = _destination_state(
        import_destination,
        raw,
        "imported ledger",
    )
    report_state = _destination_state(
        report_destination,
        report_bytes,
        "reconciliation report",
    )
    if import_state == "create":
        import_state = _write_new_or_exact(
            import_destination,
            raw,
            "imported ledger",
        )
    if report_state == "create":
        report_state = _write_new_or_exact(
            report_destination,
            report_bytes,
            "reconciliation report",
        )

    return {
        "import_state": import_state,
        "report_state": report_state,
        "imported_ledger_sha256": report["imported_ledger_sha256"],
        "imported_ledger_size": report["imported_ledger_size"],
        "reconciliation_status": reconciliation["reconciliation_status"],
        "row_disagreement_count": reconciliation["row_disagreement_count"],
        "promotion_ready": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Import the exact immutable Netto N10 visual ledger and generate "
            "a fail-closed reconciliation report."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--ledger", type=Path)
    source.add_argument("--builder-script", type=Path)
    parser.add_argument("--first-review", type=Path, required=True)
    parser.add_argument("--import-destination", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = import_and_reconcile(
            first_review_path=args.first_review,
            import_destination=args.import_destination,
            report_destination=args.report,
            ledger_path=args.ledger,
            builder_script_path=args.builder_script,
        )
    except (N10ImportError, RECONCILIATION.ReviewReconciliationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
