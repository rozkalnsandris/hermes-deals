from __future__ import annotations

from typing import Any, Mapping

CANARY_AUTH_SCHEMA_VERSION = 1
CANARY_APPLY_DECISION = "approve_lidl_v631_one_row_canary_apply"
CANARY_APPLY_SCOPE = "exact_one_row_production_db_canary"
CANARY_APPLY_PERMISSIONS = {
    "production_database_write": True,
    "max_source_snapshot_writes": 1,
    "max_offer_candidate_writes": 1,
    "review_write": False,
    "production_publish": False,
    "production_deploy": False,
    "corpus_write": False,
    "source_replacement": False,
    "systemd_change": False,
    "scheduler_change": False,
}


def build_canary_apply_authorization(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Build the exact one-row APPLY authorization payload for a validated plan."""
    bindings = plan["bindings"]
    offer = plan["offer_candidate"]
    return {
        "schema_version": CANARY_AUTH_SCHEMA_VERSION,
        "decision": CANARY_APPLY_DECISION,
        "scope": CANARY_APPLY_SCOPE,
        "payload_fingerprint": plan["payload_fingerprint"],
        "plan_fingerprint": plan["plan_fingerprint"],
        "reviewed_canary_receipt_sha256": bindings["reviewed_canary_receipt_sha256"],
        "semantic_row_key": bindings["semantic_row_key"],
        "source_offer_id": offer["source_offer_id"],
        "permissions": dict(CANARY_APPLY_PERMISSIONS),
    }


def validate_canary_apply_authorization(
    authorization: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> None:
    """Raise ValueError unless authorization is exact for this plan and scope."""
    auth = dict(authorization)
    if (
        auth.get("schema_version") != CANARY_AUTH_SCHEMA_VERSION
        or auth.get("decision") != CANARY_APPLY_DECISION
        or auth.get("scope") != CANARY_APPLY_SCOPE
    ):
        raise ValueError("apply authorization decision/scope mismatch")

    expected = {
        "payload_fingerprint": plan["payload_fingerprint"],
        "reviewed_canary_receipt_sha256": plan["bindings"]["reviewed_canary_receipt_sha256"],
        "semantic_row_key": plan["bindings"]["semantic_row_key"],
        "source_offer_id": plan["offer_candidate"]["source_offer_id"],
    }
    if any(auth.get(key) != value for key, value in expected.items()):
        raise ValueError("apply authorization stable binding mismatch")

    if plan["result"] == "READY_TO_CREATE" and auth.get("plan_fingerprint") != plan["plan_fingerprint"]:
        raise ValueError("apply authorization plan_fingerprint mismatch")
    if plan["result"] not in {"READY_TO_CREATE", "NO_OP_IDENTICAL"}:
        raise ValueError("apply authorization cannot target a blocked plan")
    if auth.get("permissions") != CANARY_APPLY_PERMISSIONS:
        raise ValueError("apply authorization permissions mismatch")
