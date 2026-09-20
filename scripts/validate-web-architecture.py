#!/usr/bin/env python3
# Validate the canonical Hermes Deals Web architecture contract.

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / ".github" / "web-architecture-v1.json"
TARGET = (
    "FastAPI + PostgreSQL + Jinja + HTMX + semantic HTML + plain CSS + "
    "minimal Vanilla JS + SSE + Cloudflare Access/Tunnel"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"WEB_ARCHITECTURE_GUARD_FAIL: {message}")


def require_text(path: str, needles: list[str]) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    for needle in needles:
        require(needle in text, f"{path} missing canonical marker: {needle!r}")


def main() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    require(contract["schema_version"] == 1, "unexpected schema_version")
    require(contract["status"] == "canonical", "contract must remain canonical")
    require(contract["repository"] == "rozkalnsandris/hermes-deals", "repository mismatch")
    require(contract["human_contract"] == "docs/WEB_ARCHITECTURE.md", "human contract mismatch")
    require(contract["system_architecture"] == "docs/ARCHITECTURE.md", "system architecture mismatch")
    require(contract["execution_tracker_issue"] == 319, "execution tracker must remain issue #319")
    require(contract["operator_contract"] == "AGENTS.md", "operator contract mismatch")
    require(contract["project_entrypoint"] == "README.md", "project entrypoint mismatch")

    expected_stack = {
        "application": "FastAPI",
        "database": "PostgreSQL",
        "templates": "Jinja",
        "interaction": "HTMX",
        "markup": "semantic HTML",
        "styling": "plain CSS",
        "client_javascript": "minimal Vanilla JS for browser-specific behavior only",
        "realtime": "Server-Sent Events (SSE)",
        "public_access": "Cloudflare Access/Tunnel",
    }
    require(contract["canonical_stack"] == expected_stack, "canonical stack drift")

    truth = contract["truth_boundaries"]
    require(truth["application_source_of_truth"] == "PostgreSQL", "PostgreSQL truth boundary drift")
    require(truth["domain_logic"] == "shared Python services", "Python domain boundary drift")
    require(truth["html_and_json_must_share_domain_services"] is True, "HTML/JSON services must stay shared")
    require(truth["browser_business_state_is_authoritative"] is False, "browser cannot become authoritative")
    require(truth["sse_events_are_authoritative"] is False, "SSE cannot become authoritative")
    require(truth["browser_business_rules_allowed"] is False, "browser business rules are not allowed")

    online = contract["online_only"]
    require(online["required"] is True, "online-only requirement drift")
    for key in (
        "offline_application_behavior",
        "indexeddb_application_state",
        "dexie",
        "offline_outbox",
        "background_sync",
        "offline_mutation_reconciliation",
        "service_worker_business_state_cache",
    ):
        require(online[key] is False, f"offline capability unexpectedly enabled: {key}")

    realtime = contract["realtime_contract"]
    require(realtime["write_transport"] == "authenticated HTTP", "write transport drift")
    require(realtime["server_to_client_transport"] == "SSE", "realtime transport drift")
    require(realtime["client_must_reread_authoritative_state_after_consequential_event"] is True, "SSE clients must reread authoritative state")
    require(realtime["websocket_default_allowed"] is False, "WebSocket cannot become the default")
    require(realtime["websocket_requires_explicit_owner_architecture_decision"] is True, "WebSocket architecture gate drift")

    build = contract["build_policy"]
    require(build["small_deterministic_build_only_tooling_allowed"] is True, "deterministic build-only tooling policy drift")
    require(build["may_create_second_production_application_runtime"] is False, "second production application runtime is forbidden")

    guard = contract["ci_guard"]
    require(guard["validator"] == "scripts/validate-web-architecture.py", "validator path drift")
    require(guard["workflow"] == ".github/workflows/web-architecture-guard.yml", "guard workflow path drift")
    require(guard["must_pass_on_pull_request"] is True, "PR guard must stay enabled")

    required_together = set(contract["change_gate"]["must_update_together"])
    require({
        "docs/ARCHITECTURE.md",
        "docs/WEB_ARCHITECTURE.md",
        ".github/web-architecture-v1.json",
        "README.md",
        "AGENTS.md",
        "GitHub issue #319",
    }.issubset(required_together), "canonical synchronized-update set drift")

    require_text("docs/ARCHITECTURE.md", [TARGET, "online-only", "Server-Sent Events (SSE)"])
    require_text("docs/WEB_ARCHITECTURE.md", [TARGET, "Canonical architecture decision", "Offline behavior is explicitly out of scope."])
    require_text("docs/ROADMAP.md", [TARGET, "Canonical Web direction"])
    require_text("AGENTS.md", [
        "Before Web presentation, UI architecture, client-state, or realtime-transport work",
        f"The canonical Web target is `{TARGET}`",
    ])
    require_text("README.md", [
        'href="docs/WEB_ARCHITECTURE.md">Web architecture</a>',
        f"| **Canonical Web target** | {TARGET} |",
        "canonical real-time target is authenticated HTTP plus SSE",
    ])
    require_text(".github/workflows/web-architecture-guard.yml", [
        "python3 scripts/validate-web-architecture.py",
    ])
    print("HERMES_WEB_ARCHITECTURE_GUARD=PASS")


if __name__ == "__main__":
    main()
