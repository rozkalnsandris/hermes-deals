#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True
from typing import Any, Iterable, Iterator, Mapping, Sequence

AUDIT_NAME = "netto-shadow-v1"
STORE_ID = "5659"
SCOPE = "family_primary_netto"
FIELDS = ("title", "brand", "package", "price", "validity", "card_ownership")
ROW_KEYS = {
    "campaign_id", "field", "expected", "predicted", "classification",
    "page_number", "card_id", "manifest_sha256", "pdf_sha256",
    "parser_identity", "store_external_id", "scope",
}
SAFE_ACTIONS = {"write_plan_ready", "run_shadow", "unchanged_noop", "safe_empty_no_pdf"}


def sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def validate_repo(repo: Path, expected_head: str) -> str:
    resolved = repo.resolve()
    if resolved != Path("/home/andris/hermes-deals") and os.environ.get("HERMES_AUDIT_TEST_MODE") != "1":
        raise ValueError("audit repository must be /home/andris/hermes-deals")
    if not (resolved / ".git").exists() or git(resolved, "branch", "--show-current") != "main":
        raise ValueError("audit repository must be a main-branch Git checkout")
    if git(resolved, "rev-parse", "HEAD") != expected_head:
        raise ValueError("audit repository HEAD mismatch")
    status = git(resolved, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise ValueError("audit repository must be clean")
    return status


def regular_files(root: Path, suffixes: Sequence[str], limit: int, depth: int) -> Iterator[Path]:
    if not root.exists():
        return
    root = root.resolve()
    count = 0
    for path in sorted(root.rglob("*")):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if len(relative.parts) > depth or path.is_symlink() or not path.is_file():
            continue
        if path.suffix.casefold() not in suffixes:
            continue
        count += 1
        if count > limit:
            raise ValueError(f"bounded scan exceeded {limit} files under {root}")
        yield path


def load_json(path: Path, max_bytes: int) -> Any:
    if path.stat().st_size > max_bytes:
        raise ValueError(f"JSON file is too large: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def looks_like_row(value: Any) -> bool:
    return isinstance(value, Mapping) and ROW_KEYS.issubset(value) and value.get("field") in FIELDS


def row_groups(value: Any) -> Iterator[list[Mapping[str, Any]]]:
    if isinstance(value, list) and value and all(looks_like_row(x) for x in value):
        yield value
    elif isinstance(value, Mapping):
        for key in ("audit_rows", "rows", "truth_rows", "evaluations", "records"):
            candidate = value.get(key)
            if isinstance(candidate, list) and candidate and all(looks_like_row(x) for x in candidate):
                yield candidate
        for candidate in value.values():
            if isinstance(candidate, Mapping):
                yield from row_groups(candidate)


def shadow_modules(repo: Path):
    tools = str(repo / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    from netto_shadow_gate import evaluate_corpus  # type: ignore
    from netto_shadow_promotion import AuditRow, EvidenceBinding, EvidenceStatus  # type: ignore
    from netto_shadow_weekly import WeeklyInput, decide_weekly_action, verify_weekly_input  # type: ignore
    return AuditRow, EvidenceBinding, EvidenceStatus, WeeklyInput, evaluate_corpus, decide_weekly_action, verify_weekly_input


def collect_corpus(repo: Path, root: Path, minimum_samples: int) -> tuple[dict[str, Any], int]:
    AuditRow, _, _, _, evaluate, _, _ = shadow_modules(repo)
    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    identities: set[str] = set()
    for path in regular_files(root, (".json", ".jsonl"), 20_000, 10):
        if "netto" not in path.as_posix().casefold():
            continue
        try:
            payload = (
                [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
                if path.suffix.casefold() == ".jsonl" else load_json(path, 32 * 1024 * 1024)
            )
            accepted = 0
            for group in row_groups(payload):
                for raw in group:
                    item = AuditRow.from_mapping(raw)
                    normalized = {
                        "campaign_id": item.campaign_id, "field": item.field,
                        "expected": item.expected, "predicted": item.predicted,
                        "classification": item.classification.value,
                        "page_number": item.page_number, "card_id": item.card_id,
                        "manifest_sha256": item.manifest_sha256,
                        "pdf_sha256": item.pdf_sha256,
                        "parser_identity": item.parser_identity,
                        "store_external_id": item.store_external_id, "scope": item.scope,
                    }
                    identity = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
                    if identity not in identities:
                        identities.add(identity); rows.append(normalized); accepted += 1
            if accepted:
                sources.append({"path": str(path), "sha256": sha_file(path), "row_count": accepted})
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            rejected.append({"path": str(path), "reason": str(exc)})
    blocked = {
        "schema_version": 1, "status": "insufficient_evidence", "row_count": len(rows),
        "source_files": sources, "rejected_files": rejected[:100], "promotion_ready": False,
        "automatic_approval_enabled": False, "automatic_publish_enabled": False,
        "production_write_performed": False,
    }
    if not rows:
        blocked["reason"] = "No valid immutable Netto AuditRow corpus was found."
        return blocked, 0
    try:
        report = evaluate(rows, minimum_samples=minimum_samples, minimum_campaigns_per_field=2)
    except ValueError as exc:
        blocked["reason"] = str(exc)
        blocked["campaign_ids"] = sorted({x["campaign_id"] for x in rows})
        return blocked, len(rows)
    report.update({
        "status": "evaluated", "source_files": sources, "rejected_files": rejected[:100],
        "promotion_ready": all(report["fields"][field]["promoted"] for field in FIELDS),
        "automatic_approval_enabled": False, "automatic_publish_enabled": False,
        "production_write_performed": False,
    })
    return report, len(rows)


def first(payload: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if payload.get(key) not in (None, ""):
            return payload[key]
    return None


def date_pair(payload: Mapping[str, Any]) -> tuple[str, str] | None:
    start, end = first(payload, ("valid_from", "start_date")), first(payload, ("valid_until", "end_date"))
    if isinstance(start, str) and isinstance(end, str):
        try:
            a, b = date.fromisoformat(start), date.fromisoformat(end)
            return (a.isoformat(), b.isoformat()) if a <= b else None
        except ValueError:
            pass
    for key in ("selected_validity", "selected_range"):
        if isinstance(payload.get(key), Mapping):
            found = date_pair(payload[key])
            if found:
                return found
    ranges = payload.get("unique_validity_ranges")
    return date_pair(ranges[0]) if isinstance(ranges, list) and len(ranges) == 1 and isinstance(ranges[0], Mapping) else None


def manifest_candidate(payload: Mapping[str, Any]) -> bool:
    return (
        str(first(payload, ("store_external_id", "store_id", "source_store_external_id")) or "") == STORE_ID
        and str(payload.get("scope") or "") == SCOPE
        and "netto" in str(payload.get("strategy") or "").casefold()
    )


LEGACY_CONTAINER_RAW_ROOT = Path("/data/raw")


def reference(manifest: Path, root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = Path(value)
    candidates: list[Path]
    fallback: Path

    if raw.is_absolute():
        candidates = [raw]
        fallback = raw
        try:
            legacy_relative = raw.relative_to(LEGACY_CONTAINER_RAW_ROOT)
        except ValueError:
            pass
        else:
            # Collector manifests were authored inside the container and may
            # retain /data/raw/... paths. Map only that exact legacy namespace
            # to the explicitly supplied host raw root. Never basename-search
            # or remap arbitrary absolute paths.
            if ".." not in legacy_relative.parts:
                mapped = root / legacy_relative
                candidates.append(mapped)
                fallback = mapped
    else:
        candidates = [manifest.parent / raw, root / raw]
        fallback = candidates[0]

    for candidate in candidates:
        if candidate.exists() or candidate.is_symlink():
            return candidate.absolute()
    return fallback.absolute()


def inspect_manifests(repo: Path, root: Path, today: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _, Binding, Status, WeeklyInput, _, decide, verify = shadow_modules(repo)
    inventory: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for manifest in regular_files(root, (".json",), 20_000, 12):
        try:
            payload = load_json(manifest, 16 * 1024 * 1024)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping) or not manifest_candidate(payload):
            continue
        dates = date_pair(payload)
        record: dict[str, Any] = {
            "manifest_path": str(manifest), "manifest_sha256": sha_file(manifest),
            "campaign_key": str(first(payload, ("campaign_key", "corpus_key", "prospect_slug")) or manifest.stem),
            "validity": list(dates) if dates else None, "binding_status": "unbound",
        }
        if not dates:
            record["binding_reason"] = "verified validity window is missing"; inventory.append(record); continue
        html = reference(manifest, root, first(payload, ("html_path", "store_html_path", "store_path", "snapshot_html_path")))
        html_sha = first(payload, ("html_sha256", "store_html_sha256", "store_sha256", "snapshot_html_sha256"))
        pdf = reference(manifest, root, first(payload, ("prospect_pdf_path", "pdf_path", "source_pdf_path")))
        pdf_sha = first(payload, ("prospect_pdf_sha256", "pdf_sha256", "source_pdf_sha256"))
        no_pdf = first(payload, ("no_pdf_reason", "prospect_no_pdf_reason"))
        if html is None or not isinstance(html_sha, str):
            record["binding_reason"] = "HTML path/SHA binding is incomplete"; inventory.append(record); continue
        initial = Status.PDF_BOUND.value if pdf and isinstance(pdf_sha, str) else Status.VERIFIED_NO_PDF.value if isinstance(no_pdf, str) else Status.MISSING.value
        binding = {
            "manifest_path": str(manifest), "manifest_sha256": record["manifest_sha256"],
            "html_path": str(html), "html_sha256": html_sha, "evidence_status": initial,
            "pdf_path": str(pdf) if pdf else None, "pdf_sha256": pdf_sha if isinstance(pdf_sha, str) else None,
            "parser_identity": str(first(payload, ("parser_identity", "parser_version", "strategy")) or "unknown"),
            "store_external_id": STORE_ID, "scope": SCOPE,
            "valid_from": dates[0], "valid_until": dates[1],
            "no_pdf_reason": no_pdf if isinstance(no_pdf, str) else None,
        }
        try:
            Binding.from_mapping(binding).validate()
            base = {
                "binding": binding, "campaign_key": record["campaign_key"],
                "previous_campaign_key": None, "previous_evidence_identity": None,
                "shadow_passed": None, "retry_count": 0, "last_success_valid_until": dates[1],
            }
            verified, reason = verify(WeeklyInput.from_mapping({**base, "today": today.isoformat()}))
            current = decide(verified)
            before = decide(WeeklyInput.from_mapping({**base, "binding": {**binding, "evidence_status": verified.binding.evidence_status.value}, "today": (date.fromisoformat(dates[0]) - timedelta(days=1)).isoformat(), "last_success_valid_until": None}))
            replay = decide(WeeklyInput.from_mapping({**base, "binding": {**binding, "evidence_status": verified.binding.evidence_status.value}, "today": dates[0], "previous_campaign_key": record["campaign_key"], "previous_evidence_identity": verified.binding.identity_sha256()}))
            record.update({"binding_status": verified.binding.evidence_status.value, "binding_reason": reason, "evidence_identity": verified.binding.identity_sha256()})
            decisions.append({
                "manifest_path": str(manifest), "campaign_key": record["campaign_key"],
                "verification_reason": reason, "before_window": asdict(before),
                "current_date": asdict(current), "unchanged_replay": asdict(replay),
                "production_write_authorized": False,
            })
        except (OSError, ValueError) as exc:
            record.update({"binding_status": "invalid", "binding_reason": str(exc)})
        inventory.append(record)
    return inventory, decisions


def transition_history(root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in regular_files(root, (".json",), 5_000, 8):
        try:
            payload = load_json(path, 4 * 1024 * 1024)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        for value in payload if isinstance(payload, list) else (payload,):
            if not isinstance(value, Mapping):
                continue
            action, campaign = str(value.get("action") or ""), str(value.get("campaign_key") or "")
            raw_time = first(value, ("recorded_at", "created_at", "completed_at", "observed_at"))
            timestamp = None
            if isinstance(raw_time, str):
                try:
                    timestamp = datetime.fromisoformat(raw_time.replace("Z", "+00:00")).isoformat()
                except ValueError:
                    pass
            if action in SAFE_ACTIONS and campaign:
                records.append({
                    "path": str(path), "sha256": sha_file(path), "campaign_key": campaign,
                    "action": action, "recorded_at": timestamp,
                    "production_write_authorized": bool(value.get("production_write_authorized", False)),
                })
    campaigns = sorted({x["campaign_key"] for x in records})
    timestamped = sorted({x["campaign_key"] for x in records if x["recorded_at"]})
    unsafe = [x for x in records if x["production_write_authorized"]]
    return {
        "state_root": str(root), "record_count": len(records), "campaign_keys": campaigns,
        "timestamped_campaign_keys": timestamped,
        "consecutive_transition_evidence_count": len(timestamped),
        "two_real_transitions_proven": len(timestamped) >= 2 and not unsafe,
        "unsafe_authorization_records": unsafe, "records": records,
    }


def policy(repo: Path) -> dict[str, Any]:
    path = repo / "backend/tests/fixtures/netto/n25_title_package_review_policy_v1.json"
    data = load_json(path, 2 * 1024 * 1024)
    return {
        "path": str(path), "sha256": sha_file(path),
        "title_full_rate": data["basis"]["combined_full_title_rate"],
        "automatic_package_selection_count": data["basis"]["automatic_package_selection_count"],
        "production_integration_allowed": data["promotion_policy"]["production_integration_allowed"],
        "title_route": data["title_policy"]["route"], "package_route": data["package_policy"]["route"],
    }


def run_audit(repo: Path, expected_head: str, audit_root: Path, raw_root: Path, state_root: Path, output: Path, today: date, minimum_samples: int = 25) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    initial = validate_repo(repo, expected_head)
    output, repo = output.resolve(), repo.resolve()
    if output == repo or repo in output.parents:
        raise ValueError("audit output must be outside the Git repository")
    output.mkdir(parents=True, exist_ok=True)
    corpus, row_count = collect_corpus(repo, audit_root, minimum_samples)
    manifests, decisions = inspect_manifests(repo, raw_root, today)
    transitions = transition_history(state_root)
    metrics = corpus.get("fields") if isinstance(corpus, Mapping) else None
    issue27 = corpus.get("status") == "evaluated" and isinstance(metrics, Mapping) and all(
        isinstance(metrics.get(field), Mapping) and int(metrics[field].get("campaign_count", 0)) >= 2 and int(metrics[field].get("audited_count", 0)) > 0
        for field in FIELDS
    )
    verified = sum(x.get("binding_status") in {"pdf_bound", "verified_no_pdf"} for x in manifests)
    issue28 = bool(transitions["two_real_transitions_proven"])
    summary = {
        "schema_version": 1, "audit": AUDIT_NAME, "strategy": "netto_rpi5_shadow_evidence_v1",
        "started_at": started.isoformat(), "completed_at": datetime.now(timezone.utc).isoformat(),
        "repository": str(repo), "commit_sha": expected_head, "today": today.isoformat(),
        "policy_binding": policy(repo), "corpus_status": corpus.get("status"),
        "corpus_row_count": row_count, "corpus_campaign_count": int(corpus.get("campaign_count", 0)),
        "manifest_candidate_count": len(manifests), "verified_manifest_count": verified,
        "weekly_decision_count": len(decisions), "issue_27_real_corpus_evidence_ready": issue27,
        "issue_28_two_real_transitions_ready": issue28, "result": "pass",
        "acceptance_status": "ready" if issue27 and issue28 else "blocked",
        "blocking_reasons": [reason for ok, reason in (
            (issue27, "immutable multi-campaign AuditRow corpus is not yet sufficient"),
            (verified > 0, "no fully verified Netto manifest/HTML/PDF binding was found"),
            (issue28, "two timestamped real unattended shadow transitions are not yet proven"),
        ) if not ok],
        "production_apply_authorized": False, "production_write_performed": False,
        "database_write_performed": False, "deployment_performed": False,
        "systemd_units_installed": False, "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
    }
    for name, value in (
        ("corpus-report.json", corpus), ("evidence-inventory.json", {"manifests": manifests}),
        ("weekly-decisions.json", decisions), ("transition-history.json", transitions),
        ("audit-summary.json", summary),
    ):
        atomic_json(output / name, value)
    if git(repo, "status", "--porcelain=v1", "--untracked-files=all") != initial:
        raise RuntimeError("audit changed the repository worktree")
    generated = [{"path": p.name, "bytes": p.stat().st_size, "sha256": sha_file(p)} for p in sorted(output.iterdir()) if p.is_file() and not p.is_symlink()]
    atomic_json(output / "audit-artifact-manifest.json", {
        "audit": AUDIT_NAME, "commit_sha": expected_head, "generated_files": generated,
        "production_apply_authorized": False,
    })
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only RPi5 Netto shadow evidence audit")
    parser.add_argument("--repo", type=Path, default=Path("/home/andris/hermes-deals"))
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--audit-root", type=Path, default=Path("/home/andris/hermes-deals-audits"))
    parser.add_argument("--raw-root", type=Path, default=Path("/home/andris/hermes-deals/data/raw"))
    parser.add_argument("--state-root", type=Path, default=Path("/var/lib/hermes-deals/netto-weekly-shadow"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    parser.add_argument("--minimum-samples", type=int, default=25)
    args = parser.parse_args()
    try:
        result = run_audit(args.repo, args.expected_head, args.audit_root, args.raw_root, args.state_root, args.output, args.today, args.minimum_samples)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR|{exc}", file=sys.stderr); return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
