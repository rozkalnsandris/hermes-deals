from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from typing import Iterator

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.edeka_normalization_audit import (
    audit_edeka_manifest,
    write_deterministic_report,
)
from app.edeka_store_offers import (
    collect_edeka_store_offers,
    parse_edeka_store_offers_snapshot,
    _read_manifest_bytes,
    _validate_source,
)
from app.models import Base, OfferCandidateRecord, SourceSnapshot
from app.offer_store import save_offer_candidates
from app.parsers.edeka import EdekaParserContext
from app.source_config import SourceConfig, load_sources


CAPTURE_SCHEMA_VERSION = 1
EXPECTED_SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
EXPECTED_PUBLIC_MARKET_ID = "071897"
EXPECTED_INTERNAL_MARKET_ID = "587881"
EXPECTED_STORE_NAME = "EDEKA Patzer"
EXPECTED_SCOPE = "family_primary_edeka"


def _stable_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_exclusive_json(path: Path, value: object) -> None:
    data = _stable_json_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError(f"Refusing to replace different shadow evidence: {path}")


def _prepare_output_directory(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.exists():
        if resolved.is_symlink() or not resolved.is_dir():
            raise ValueError("EDEKA shadow output path is not a safe directory")
        if any(resolved.iterdir()):
            raise ValueError("EDEKA shadow output directory must be empty")
    else:
        resolved.mkdir(parents=True, mode=0o700)
    return resolved


def _relative_under(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"EDEKA shadow evidence escaped output directory: {resolved}"
        ) from exc


def _exact_source(path: Path) -> SourceConfig:
    matches = [
        source
        for source in load_sources(path)
        if source.enabled and source.chain == "edeka"
    ]
    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one enabled EDEKA source for shadow capture, "
            f"found={len(matches)}"
        )
    source = matches[0]
    _validate_source(source)
    return source


def _manifest_collected_at(manifest: dict[str, object]) -> datetime:
    value = manifest.get("collected_at")
    if not isinstance(value, str):
        raise ValueError("EDEKA shadow manifest collected_at is missing")
    try:
        collected_at = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("EDEKA shadow manifest collected_at is invalid") from exc
    if collected_at.tzinfo is None or collected_at.utcoffset() is None:
        raise ValueError("EDEKA shadow manifest collected_at must be timezone-aware")
    return collected_at.astimezone(timezone.utc)


@contextmanager
def _temporary_environment(values: dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _file_record(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": _relative_under(path, root),
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _write_sha256s(root: Path, paths: list[Path]) -> Path:
    target = root / "SHA256SUMS"
    lines = [
        f"{_sha256_file(path)}  {_relative_under(path, root)}"
        for path in sorted(paths, key=lambda item: _relative_under(item, root))
    ]
    data = ("\n".join(lines) + "\n").encode("utf-8")
    with target.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return target


def capture_edeka_shadow_cycle(
    output_dir: Path,
    sources_config: Path,
    *,
    min_offers: int = 150,
) -> dict[str, object]:
    if min_offers <= 0:
        raise ValueError("EDEKA shadow minimum offer count must be positive")

    root = _prepare_output_directory(output_dir)
    sources_path = sources_config.expanduser().resolve()
    if not sources_path.is_file() or sources_path.is_symlink():
        raise ValueError("EDEKA shadow sources config is missing or unsafe")
    source = _exact_source(sources_path)

    raw_dir = root / "raw"
    raw_dir.mkdir(mode=0o700)
    database_path = root / "shadow.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"

    environment = {
        "APP_ENV": "edeka-shadow",
        "DATABASE_URL": database_url,
        "RAW_SNAPSHOT_DIR": str(raw_dir),
        "SOURCES_CONFIG": str(sources_path),
    }

    snapshot: SourceSnapshot
    manifest_path: Path
    manifest: dict[str, object]
    manifest_collected_at: datetime
    offers_count = 0
    first_write_count = 0
    replay_write_count = 0
    source_snapshot_count = 0
    persisted_offer_count = 0

    with _temporary_environment(environment):
        engine = create_engine(database_url)
        try:
            Base.metadata.create_all(engine)
            with Session(engine, expire_on_commit=False) as db:
                collection = collect_edeka_store_offers(db, source)
                snapshot = collection.snapshot
                if collection.unchanged:
                    raise ValueError(
                        "A fresh isolated shadow database unexpectedly returned unchanged"
                    )
                if (
                    not snapshot.success
                    or not snapshot.snapshot_path
                    or not snapshot.sha256
                ):
                    raise ValueError(
                        "EDEKA shadow source collection failed: "
                        f"{snapshot.error or snapshot.http_status}"
                    )

                manifest_path = Path(snapshot.snapshot_path).resolve()
                _relative_under(manifest_path, root)
                manifest = _read_manifest_bytes(
                    manifest_path,
                    snapshot.sha256,
                )
                manifest_collected_at = _manifest_collected_at(manifest)

                context = EdekaParserContext(
                    snapshot_id=snapshot.id,
                    source_url=snapshot.final_url or snapshot.source_url,
                    collected_at=manifest_collected_at,
                    public_market_id=source.store_external_id or "",
                    internal_market_id=source.store_internal_id or "",
                    store_name=source.store_name or "",
                )
                offers = parse_edeka_store_offers_snapshot(
                    manifest_path,
                    snapshot.sha256,
                    context,
                )
                offers_count = len(offers)
                if offers_count < min_offers:
                    raise ValueError(
                        "EDEKA shadow parser output is below the production-scale "
                        f"gate: offers={offers_count} minimum={min_offers}"
                    )

                first_write_count = save_offer_candidates(db, offers)
                replay_write_count = save_offer_candidates(db, offers)
                source_snapshot_count = int(
                    db.scalar(select(func.count()).select_from(SourceSnapshot)) or 0
                )
                persisted_offer_count = int(
                    db.scalar(
                        select(func.count()).select_from(OfferCandidateRecord)
                    )
                    or 0
                )
        finally:
            engine.dispose()

    if first_write_count != offers_count:
        raise ValueError(
            "EDEKA shadow first persistence delta mismatch: "
            f"written={first_write_count} offers={offers_count}"
        )
    if replay_write_count != 0:
        raise ValueError(
            "EDEKA shadow identical replay wrote duplicate rows: "
            f"delta={replay_write_count}"
        )
    if source_snapshot_count != 1:
        raise ValueError(
            "EDEKA shadow isolated database snapshot count mismatch: "
            f"count={source_snapshot_count}"
        )
    if persisted_offer_count != offers_count:
        raise ValueError(
            "EDEKA shadow isolated database offer count mismatch: "
            f"persisted={persisted_offer_count} parsed={offers_count}"
        )

    raw_path_value = manifest.get("raw_html_path")
    if not isinstance(raw_path_value, str):
        raise ValueError("EDEKA shadow manifest raw HTML path is missing")
    raw_path = Path(raw_path_value).resolve()
    _relative_under(raw_path, root)

    normalization = audit_edeka_manifest(manifest_path, snapshot.sha256)
    normalization_path = root / "normalization-report.json"
    write_deterministic_report(normalization_path, normalization)

    source_summary = normalization.get("source")
    normalization_summary = normalization.get("summary")
    if not isinstance(source_summary, dict) or not isinstance(
        normalization_summary,
        dict,
    ):
        raise ValueError("EDEKA shadow normalization report is incomplete")

    core_files = {
        "manifest": _file_record(manifest_path, root),
        "raw_html": _file_record(raw_path, root),
        "normalization_report": _file_record(normalization_path, root),
        "isolated_database": _file_record(database_path, root),
    }
    evidence: dict[str, object] = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "audit_type": "edeka_single_shadow_cycle_capture",
        "result": "pass",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "source_chain": "edeka",
            "scope": EXPECTED_SCOPE,
            "public_market_id": EXPECTED_PUBLIC_MARKET_ID,
            "internal_market_id": EXPECTED_INTERNAL_MARKET_ID,
            "store_name": EXPECTED_STORE_NAME,
            "source_url": EXPECTED_SOURCE_URL,
            "snapshot_id": str(snapshot.id),
            "collected_at": manifest_collected_at.isoformat(),
            "valid_from": source_summary.get("valid_from"),
            "valid_until": source_summary.get("valid_until"),
            "parser_version": source_summary.get("parser_version"),
            "manifest_sha256": snapshot.sha256,
            "raw_html_sha256": manifest.get("raw_html_sha256"),
        },
        "normalization": {
            "normalizer_version": normalization.get("normalizer_version"),
            "resolved_count": normalization_summary.get("resolved_count"),
            "review_required_count": normalization_summary.get(
                "review_required_count"
            ),
            "rows_sha256": normalization_summary.get("rows_sha256"),
            "report_sha256": normalization.get("report_sha256"),
        },
        "isolated_persistence": {
            "database_engine": "sqlite",
            "source_snapshot_count": source_snapshot_count,
            "parsed_offer_count": offers_count,
            "first_write_offer_delta": first_write_count,
            "same_snapshot_replay_offer_delta": replay_write_count,
            "persisted_offer_count": persisted_offer_count,
            "production_database_write": False,
        },
        "safety": {
            "production_deployment": False,
            "production_database_write": False,
            "review_write": False,
            "publication_write": False,
            "scheduler_activation": False,
        },
        "files": core_files,
    }
    evidence["evidence_sha256"] = sha256(_stable_json_bytes(evidence)).hexdigest()

    evidence_path = root / "cycle-evidence.json"
    _write_exclusive_json(evidence_path, evidence)
    sums_path = _write_sha256s(
        root,
        [
            manifest_path,
            raw_path,
            normalization_path,
            database_path,
            evidence_path,
        ],
    )

    return {
        "result": "pass",
        "output_dir": str(root),
        "cycle_evidence": str(evidence_path),
        "sha256s": str(sums_path),
        "snapshot_id": str(snapshot.id),
        "valid_from": source_summary.get("valid_from"),
        "valid_until": source_summary.get("valid_until"),
        "offer_count": offers_count,
        "first_write_offer_delta": first_write_count,
        "same_snapshot_replay_offer_delta": replay_write_count,
        "evidence_sha256": evidence["evidence_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Capture one EDEKA Patzer weekly cycle into isolated SQLite and "
            "immutable shadow evidence"
        )
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sources-config", type=Path, required=True)
    parser.add_argument("--min-offers", type=int, default=150)
    args = parser.parse_args()

    try:
        result = capture_edeka_shadow_cycle(
            args.output_dir,
            args.sources_config,
            min_offers=args.min_offers,
        )
    except Exception as exc:
        failure = {
            "result": "fail",
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "production_database_write": False,
        }
        try:
            if args.output_dir.exists() and args.output_dir.is_dir():
                _write_exclusive_json(
                    args.output_dir / "capture-failure.json",
                    failure,
                )
        except Exception:
            pass
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
