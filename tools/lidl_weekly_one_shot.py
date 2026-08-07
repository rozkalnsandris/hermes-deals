from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, "/repo/backend")
sys.path.insert(0, "/repo/tools")
sys.path.insert(0, "/repo/tools/lidl_parser_provenance")

from app.lidl_family_source_discovery import (  # noqa: E402
    FLYER_API_URL,
    HUB_URL,
    FlyerEvidence,
    LidlFamilyDiscoveryError,
    StoreBinding,
    berlin_today,
    discover_selected_store_flyers,
    selected_store_cookies,
    write_discovery_evidence,
)
from app.lidl_weekly_completeness_contract import (  # noqa: E402
    WEEKLY_PAGE_ROLE_REVIEWED_STATUSES,
    WeeklyTargetProfileGate,
    require_weekly_target_profile,
)
from lidl_parser_provenance.lidl_v631_runtime import (  # noqa: E402
    PARSER_VERSION,
    SHADOW_SHA256,
    load_lidl_v631,
)


WORKFLOW_VERSION = "lidl-family-weekly-one-shot-v1"
EXIT_CODES = {
    "READY": 0,
    "WAIT_SOURCE": 20,
    "WAIT_SCAN": 21,
    "WAIT_PROFILE": 22,
    "WAIT_SOURCE_REVIEW": 23,
    "BLOCKED_SOURCE_DRIFT": 30,
    "BLOCKED_PARSER_DRIFT": 31,
}


@dataclass(frozen=True)
class CorpusMatch:
    flyer_dir: Path
    flyer_key: str
    scan: str | None
    source_pdf_sha256: str
    source_raw_sha256: str
    live_raw_sha256: str
    raw_refresh: bool
    stable_source_identity_sha256: str
    parser_input_identity_sha256: str
    live_parser_input_identity_sha256: str
    parser_input_changed: bool


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


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


def load_discovery_evidence(
    discovery_dir: Path,
) -> tuple[dict[str, Any], dict[str, FlyerEvidence]]:
    root = discovery_dir.resolve()
    summary = json.loads((root / "discovery.json").read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise RuntimeError("discovery.json must contain an object")
    evidence: dict[str, FlyerEvidence] = {}
    for target in ("current", "next"):
        target_root = root / f"family-{target}"
        if not target_root.is_dir():
            continue
        meta = json.loads((target_root / "meta.json").read_text(encoding="utf-8"))
        pdf = (target_root / "source.pdf").read_bytes()
        raw = (target_root / "source.json").read_bytes()
        if sha256(pdf).hexdigest() != meta.get("pdf_sha256"):
            raise RuntimeError(f"discovery PDF SHA drift for {target}")
        if sha256(raw).hexdigest() != meta.get("raw_sha256"):
            raise RuntimeError(f"discovery raw SHA drift for {target}")
        evidence[target] = FlyerEvidence(
            target=target,
            flyer_identifier=str(meta["flyer_identifier"]),
            route_region=str(meta["route_region"]),
            valid_from=str(meta["valid_from"]),
            valid_until=str(meta["valid_until"]),
            viewer_url=str(meta["viewer_url"]),
            viewer_final_url=str(meta["viewer_final_url"]),
            official_flyer_id=str(meta["official_flyer_id"]),
            document_url=str(meta["document_url"]),
            advertised_regions=tuple(str(v) for v in meta["advertised_regions"]),
            pdf_sha256=str(meta["pdf_sha256"]),
            raw_sha256=str(meta["raw_sha256"]),
            pdf_bytes=int(meta["pdf_bytes"]),
            raw_bytes=int(meta["raw_bytes"]),
            page_count=int(meta["page_count"]),
            source_pdf=pdf,
            source_json=raw,
        )
    return summary, evidence


def source_readiness(source_json: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(source_json)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {
            "state": "BLOCKED_SOURCE_DRIFT",
            "reason": f"source_json_invalid:{type(exc).__name__}",
            "discoverable": None,
            "product_link_count": 0,
            "page_count": 0,
            "nonfood_signal": False,
        }
    if not isinstance(payload, Mapping):
        return {
            "state": "BLOCKED_SOURCE_DRIFT",
            "reason": "source_json_not_object",
            "discoverable": None,
            "product_link_count": 0,
            "page_count": 0,
            "nonfood_signal": False,
        }
    flyer = payload.get("flyer")
    if not isinstance(flyer, Mapping):
        return {
            "state": "BLOCKED_SOURCE_DRIFT",
            "reason": "flyer_object_missing",
            "discoverable": None,
            "product_link_count": 0,
            "page_count": 0,
            "nonfood_signal": False,
        }

    pages = flyer.get("pages") or []
    if not isinstance(pages, list):
        pages = []
    product_link_count = 0
    for page in pages:
        if not isinstance(page, Mapping):
            continue
        links = page.get("links") or []
        if not isinstance(links, list):
            continue
        for link in links:
            if not isinstance(link, Mapping):
                continue
            display_type = str(link.get("displayType") or "").casefold()
            details = link.get("productDetails")
            if display_type == "product" or isinstance(details, Mapping):
                product_link_count += 1

    discoverable = flyer.get("discoverable")
    text = json.dumps(flyer, ensure_ascii=False).casefold()
    nonfood_signal = "nonfood" in text or "non-food" in text

    if discoverable is False and product_link_count == 0:
        return {
            "state": "WAIT_SOURCE",
            "reason": "discoverable_false_without_product_links",
            "discoverable": False,
            "product_link_count": 0,
            "page_count": len(pages),
            "nonfood_signal": nonfood_signal,
        }
    if not pages:
        return {
            "state": "WAIT_SOURCE",
            "reason": "source_has_no_pages",
            "discoverable": discoverable,
            "product_link_count": product_link_count,
            "page_count": 0,
            "nonfood_signal": nonfood_signal,
        }
    return {
        "state": "SOURCE_AVAILABLE",
        "reason": "source_payload_usable",
        "discoverable": discoverable,
        "product_link_count": product_link_count,
        "page_count": len(pages),
        "nonfood_signal": nonfood_signal,
    }


def _stable_source_identity(source_json: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(source_json)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"source JSON is invalid: {type(exc).__name__}") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError("source JSON must contain an object")
    flyer = payload.get("flyer")
    if not isinstance(flyer, Mapping):
        raise RuntimeError("source JSON flyer object is missing")

    viewer_url = str(flyer.get("flyerUrlAbsolute") or "")
    document_url = str(flyer.get("hiResPdfUrl") or flyer.get("pdfUrl") or "")
    regions = sorted(
        str(row.get("code"))
        for row in (flyer.get("regions") or [])
        if isinstance(row, Mapping) and row.get("code") is not None
    )
    pages = flyer.get("pages") or []
    if not isinstance(pages, list):
        raise RuntimeError("source JSON pages must be a list")

    identity = {
        "official_flyer_id": str(flyer.get("id") or ""),
        "viewer_path": urlsplit(viewer_url).path,
        "document_path": urlsplit(document_url).path,
        "valid_from": str(flyer.get("offerStartDate") or ""),
        "valid_until": str(flyer.get("offerEndDate") or ""),
        "advertised_regions": regions,
        "page_count": len(pages),
    }
    required = (
        "official_flyer_id",
        "viewer_path",
        "document_path",
        "valid_from",
        "valid_until",
    )
    missing = [key for key in required if not identity[key]]
    if missing:
        raise RuntimeError("stable source identity is incomplete: " + ",".join(missing))
    return identity


def _identity_digest(identity: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _canonical_parser_input(source_json: bytes) -> Mapping[str, Any]:
    try:
        payload = json.loads(source_json)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"source JSON is invalid: {type(exc).__name__}") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError("source JSON must contain an object")
    canonical = dict(payload)
    canonical.pop("dateTime", None)
    canonical.pop("warnings", None)
    return canonical


def _parser_input_identity(source_json: bytes) -> str:
    return _identity_digest(_canonical_parser_input(source_json))


def find_corpus_match(
    corpus: Path,
    *,
    pdf_sha256: str,
    live_source_json: bytes,
) -> CorpusMatch | None:
    flyers = corpus / "flyers"
    if not flyers.is_dir():
        return None
    live_identity = _stable_source_identity(live_source_json)
    live_identity_digest = _identity_digest(live_identity)
    live_raw_sha256 = sha256(live_source_json).hexdigest()
    live_parser_input_identity = _parser_input_identity(live_source_json)
    matches: list[CorpusMatch] = []
    for flyer_dir in sorted(path for path in flyers.iterdir() if path.is_dir()):
        pdf = flyer_dir / "source.pdf"
        raw = flyer_dir / "source.json"
        if not pdf.is_file() or not raw.is_file():
            continue
        if _sha256(pdf) != pdf_sha256:
            continue
        corpus_source_json = raw.read_bytes()
        corpus_identity = _stable_source_identity(corpus_source_json)
        if corpus_identity != live_identity:
            raise RuntimeError(
                "live source stable identity does not match the immutable corpus "
                f"for PDF {pdf_sha256}: live={live_identity!r} "
                f"corpus={corpus_identity!r}"
            )
        corpus_parser_input_identity = _parser_input_identity(corpus_source_json)
        scans_root = flyer_dir / "scans"
        scans = []
        if scans_root.is_dir():
            scans = sorted(
                path.name
                for path in scans_root.iterdir()
                if path.is_dir() and path.name.startswith("scan-")
            )
        corpus_raw_sha256 = sha256(corpus_source_json).hexdigest()
        matches.append(
            CorpusMatch(
                flyer_dir=flyer_dir,
                flyer_key=flyer_dir.name,
                scan=scans[-1] if scans else None,
                source_pdf_sha256=pdf_sha256,
                source_raw_sha256=corpus_raw_sha256,
                live_raw_sha256=live_raw_sha256,
                raw_refresh=corpus_raw_sha256 != live_raw_sha256,
                stable_source_identity_sha256=live_identity_digest,
                parser_input_identity_sha256=corpus_parser_input_identity,
                live_parser_input_identity_sha256=live_parser_input_identity,
                parser_input_changed=(
                    corpus_parser_input_identity != live_parser_input_identity
                ),
            )
        )
    if len(matches) > 1:
        raise RuntimeError(
            "multiple immutable corpus flyers have the same PDF identity: "
            + ",".join(row.flyer_key for row in matches)
        )
    return matches[0] if matches else None


def _status_payload(
    *,
    state: str,
    reason: str,
    target: str,
    today: date,
    discovery: Mapping[str, Any],
    source: Mapping[str, Any] | None = None,
    corpus_match: CorpusMatch | None = None,
    review_profile: Mapping[str, Any] | None = None,
    completeness_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "workflow_version": WORKFLOW_VERSION,
        "result": state,
        "reason": reason,
        "target": target,
        "today_berlin": today.isoformat(),
        "store_external_id": discovery.get("store_external_id"),
        "route_region_hardcoded": discovery.get("route_region_hardcoded"),
        "source": dict(source or {}),
        "corpus_match": (
            {
                **asdict(corpus_match),
                "flyer_dir": str(corpus_match.flyer_dir),
            }
            if corpus_match is not None
            else None
        ),
        "review_profile": dict(review_profile or {}),
        "completeness_manifest": dict(completeness_manifest or {}),
        "parser_version": PARSER_VERSION,
        "parser_sha256": SHADOW_SHA256,
        "dry_run": True,
        "corpus_write": False,
        "db_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "systemd_change": False,
    }
    return payload


def run_one_shot(
    *,
    corpus: Path,
    output_dir: Path,
    target: str,
    today: date,
    binding: StoreBinding,
    discovery_dir: Path | None = None,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise RuntimeError(f"output directory must be empty: {output_dir}")

    if discovery_dir is not None:
        discovery, evidence = load_discovery_evidence(discovery_dir)
        if discovery.get("today_berlin") != today.isoformat():
            raise RuntimeError("discovery evidence Berlin date mismatch")
        _atomic_json(
            output_dir / "discovery-reference.json",
            {
                "discovery_dir": str(discovery_dir.resolve()),
                "today_berlin": today.isoformat(),
                "targets": discovery.get("targets", {}),
            },
        )
    else:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "Chrome/150 Safari/537.36 HermesDeals-WeeklyOneShot"
            ),
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.4",
        }
        transport = httpx.HTTPTransport(retries=1)
        timeout = httpx.Timeout(90.0, connect=30.0)
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers=headers,
            cookies=selected_store_cookies(binding),
            transport=transport,
            trust_env=False,
        ) as client:
            discovery, evidence = discover_selected_store_flyers(
                client,
                binding=binding,
                today=today,
                hub_url=HUB_URL,
                api_url=FLYER_API_URL,
            )
        write_discovery_evidence(
            output_dir / "discovery",
            summary=discovery,
            evidence=evidence,
        )

    selected = evidence.get(target)
    source_meta = dict(discovery.get("targets", {}).get(target) or {})
    if selected is None:
        payload = _status_payload(
            state="WAIT_SOURCE",
            reason="selected_store_target_not_available",
            target=target,
            today=today,
            discovery=discovery,
            source=source_meta,
        )
        _atomic_json(output_dir / "one-shot-status.json", payload)
        return payload

    readiness = source_readiness(selected.source_json)
    source_meta["readiness"] = readiness
    if readiness["state"] != "SOURCE_AVAILABLE":
        payload = _status_payload(
            state=str(readiness["state"]),
            reason=str(readiness["reason"]),
            target=target,
            today=today,
            discovery=discovery,
            source=source_meta,
        )
        _atomic_json(output_dir / "one-shot-status.json", payload)
        return payload

    try:
        match = find_corpus_match(
            corpus,
            pdf_sha256=selected.pdf_sha256,
            live_source_json=selected.source_json,
        )
    except RuntimeError as exc:
        payload = _status_payload(
            state="BLOCKED_SOURCE_DRIFT",
            reason=f"corpus_stable_identity_mismatch:{exc}",
            target=target,
            today=today,
            discovery=discovery,
            source=source_meta,
        )
        _atomic_json(output_dir / "one-shot-status.json", payload)
        return payload
    if match is None:
        payload = _status_payload(
            state="WAIT_SOURCE",
            reason="exact_source_not_archived_in_immutable_corpus",
            target=target,
            today=today,
            discovery=discovery,
            source=source_meta,
        )
        _atomic_json(output_dir / "one-shot-status.json", payload)
        return payload
    if match.parser_input_changed:
        payload = _status_payload(
            state="WAIT_SOURCE_REVIEW",
            reason="parser_input_identity_changed_for_existing_pdf",
            target=target,
            today=today,
            discovery=discovery,
            source=source_meta,
            corpus_match=match,
        )
        _atomic_json(output_dir / "one-shot-status.json", payload)
        return payload
    if match.scan is None:
        payload = _status_payload(
            state="WAIT_SCAN",
            reason="authoritative_scan_missing",
            target=target,
            today=today,
            discovery=discovery,
            source=source_meta,
            corpus_match=match,
        )
        _atomic_json(output_dir / "one-shot-status.json", payload)
        return payload

    try:
        summary = json.loads(
            (match.flyer_dir / "scans" / match.scan / "summary.json").read_text(
                encoding="utf-8"
            )
        )
        if not isinstance(summary, Mapping):
            raise TypeError("scan summary is not an object")
        page_count = int(selected.page_count)
        if page_count <= 0:
            raise ValueError("selected source page_count is invalid")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        payload = _status_payload(
            state="BLOCKED_SOURCE_DRIFT",
            reason=f"authoritative_scan_summary_invalid:{type(exc).__name__}",
            target=target,
            today=today,
            discovery=discovery,
            source=source_meta,
            corpus_match=match,
        )
        _atomic_json(output_dir / "one-shot-status.json", payload)
        return payload

    try:
        profile = require_weekly_target_profile(
            match.flyer_dir,
            page_count=page_count,
        )
    except WeeklyTargetProfileGate as exc:
        payload = _status_payload(
            state=exc.result,
            reason=str(exc),
            target=target,
            today=today,
            discovery=discovery,
            source=source_meta,
            corpus_match=match,
        )
        _atomic_json(output_dir / "one-shot-status.json", payload)
        return payload

    try:
        load_lidl_v631()
    except Exception as exc:
        payload = _status_payload(
            state="BLOCKED_PARSER_DRIFT",
            reason=f"v631_integrity_gate_failed:{type(exc).__name__}:{exc}",
            target=target,
            today=today,
            discovery=discovery,
            source=source_meta,
            corpus_match=match,
            review_profile=profile,
        )
        _atomic_json(output_dir / "one-shot-status.json", payload)
        return payload

    completeness_dir = output_dir / "completeness"
    command = [
        sys.executable,
        "/repo/tools/lidl-weekly-completeness.py",
        "--flyer-dir",
        f"/corpus/flyers/{match.flyer_key}",
        "--scan",
        match.scan,
        "--output-dir",
        str(completeness_dir),
        "--no-ocr",
    ]
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    (output_dir / "completeness.stdout.log").write_text(
        completed.stdout,
        encoding="utf-8",
    )
    (output_dir / "completeness.stderr.log").write_text(
        completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        payload = _status_payload(
            state="BLOCKED_PARSER_DRIFT",
            reason=f"completeness_exit_{completed.returncode}",
            target=target,
            today=today,
            discovery=discovery,
            source=source_meta,
            corpus_match=match,
            review_profile=profile,
        )
        _atomic_json(output_dir / "one-shot-status.json", payload)
        return payload

    manifest = json.loads((completeness_dir / "manifest.json").read_text(encoding="utf-8"))
    expected = {
        "parser_version": PARSER_VERSION,
        "parser_sha256": SHADOW_SHA256,
        "page_gate_source": "review_profile",
        "review_profile_page_role_reviewed": True,
        "auto_seed_review": False,
        "auto_publish": False,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            payload = _status_payload(
                state="BLOCKED_PARSER_DRIFT",
                reason=f"completeness_manifest_mismatch:{key}",
                target=target,
                today=today,
                discovery=discovery,
                source=source_meta,
                corpus_match=match,
                review_profile=profile,
                completeness_manifest=manifest,
            )
            _atomic_json(output_dir / "one-shot-status.json", payload)
            return payload

    if manifest.get("review_profile_status") not in WEEKLY_PAGE_ROLE_REVIEWED_STATUSES:
        payload = _status_payload(
            state="BLOCKED_PARSER_DRIFT",
            reason="completeness_manifest_mismatch:review_profile_status",
            target=target,
            today=today,
            discovery=discovery,
            source=source_meta,
            corpus_match=match,
            review_profile=profile,
            completeness_manifest=manifest,
        )
        _atomic_json(output_dir / "one-shot-status.json", payload)
        return payload

    payload = _status_payload(
        state="READY",
        reason="selected_store_source_scan_profile_and_v631_ready",
        target=target,
        today=today,
        discovery=discovery,
        source=source_meta,
        corpus_match=match,
        review_profile=profile,
        completeness_manifest=manifest,
    )
    _atomic_json(output_dir / "one-shot-status.json", payload)
    return payload


def _date_arg(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only selected-store Lidl discovery and exact-corpus V6.3.1 "
            "weekly completeness dry-run."
        )
    )
    parser.add_argument("--corpus", type=Path, default=Path("/corpus"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target", choices=("current", "next"), default="next")
    parser.add_argument("--today", type=_date_arg, default=berlin_today())
    parser.add_argument("--discovery-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run_one_shot(
            corpus=args.corpus,
            output_dir=args.output_dir,
            target=args.target,
            today=args.today,
            binding=StoreBinding(),
            discovery_dir=args.discovery_dir,
        )
    except LidlFamilyDiscoveryError as exc:
        payload = {
            "schema_version": 1,
            "workflow_version": WORKFLOW_VERSION,
            "result": "BLOCKED_SOURCE_DRIFT",
            "reason": str(exc),
            "target": args.target,
            "today_berlin": args.today.isoformat(),
            "dry_run": True,
            "corpus_write": False,
            "db_write": False,
            "review_seed": False,
            "auto_approve": False,
            "auto_publish": False,
            "systemd_change": False,
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        _atomic_json(args.output_dir / "one-shot-status.json", payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    print(f"RESULT={payload['result']}")
    return EXIT_CODES.get(str(payload["result"]), 1)


if __name__ == "__main__":
    raise SystemExit(main())
