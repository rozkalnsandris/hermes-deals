from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from app.kaufland_evidence_freeze import FreezeBundle, FreezeFamily
from app.kaufland_source_discovery import (
    STORE_ADDRESS,
    STORE_ID,
    STORE_NAME,
    STORE_POSTCODE_CITY,
    KauflandSourceDiscoveryError,
)

AUTHORIZATION_SCHEMA_VERSION = 1
AUTHORIZATION_CONTRACT_VERSION = "kaufland-k2-retained-freeze-authorization-v1"


def _stable_sha(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _family_authorization_payload(family: FreezeFamily) -> dict[str, object]:
    preflight = family.preflight
    raw = family.raw
    if not preflight.store_bound:
        raise KauflandSourceDiscoveryError(
            "STORE_BINDING_NOT_PROVEN",
            "K2 authorization identity requires exact-store-bound families",
        )
    if (
        raw.requested_url != preflight.requested_url
        or raw.final_url != preflight.final_url
        or raw.content_type != preflight.content_type
        or raw.byte_count != preflight.byte_count
        or raw.sha256 != preflight.sha256
        or raw.redirects != preflight.redirects
    ):
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_IDENTITY_MISMATCH",
            "K2 authorization family raw evidence does not match its preflight identity",
        )
    return {
        "freeze_key": preflight.freeze_key,
        "source_identifier": preflight.source_identifier,
        "relation": preflight.relation,
        "valid_from": preflight.valid_from,
        "valid_to": preflight.valid_to,
        "preview": preflight.preview,
        "requested_url": preflight.requested_url,
        "final_url": preflight.final_url,
        "content_type": preflight.content_type,
        "byte_count": preflight.byte_count,
        "sha256": preflight.sha256,
        "redirects": [asdict(item) for item in preflight.redirects],
        "identity_sha256": preflight.identity_sha256,
    }


def authorization_identity_payload(bundle: FreezeBundle) -> dict[str, object]:
    families = [
        _family_authorization_payload(item)
        for item in sorted(
            bundle.families,
            key=lambda value: (
                value.preflight.valid_from,
                value.preflight.valid_to,
                value.preflight.source_identifier,
                value.preflight.identity_sha256,
            ),
        )
    ]
    if not families:
        raise KauflandSourceDiscoveryError(
            "INSUFFICIENT_K2_FAMILIES",
            "K2 authorization identity requires at least one exact-store family",
        )
    return {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "contract_version": AUTHORIZATION_CONTRACT_VERSION,
        "git_revision": bundle.git_revision,
        "store_id": STORE_ID,
        "store_name": STORE_NAME,
        "address": STORE_ADDRESS,
        "postcode_city": STORE_POSTCODE_CITY,
        "parser_input_contract_version": bundle.parser_input_contract_version,
        "families": families,
    }


def authorization_identity_sha256(bundle: FreezeBundle) -> str:
    return _stable_sha(authorization_identity_payload(bundle))
