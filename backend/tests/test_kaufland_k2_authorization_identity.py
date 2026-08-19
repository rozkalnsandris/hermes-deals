import hashlib
from dataclasses import replace

import pytest

from app.kaufland_evidence_authorization import authorization_identity_sha256
from app.kaufland_evidence_freeze import (
    CapturedArtifact,
    FreezeBundle,
    FreezeFamily,
    bundle_identity_sha256,
)
from app.kaufland_evidence_preflight import K2FamilyPreflight, K2SkippedLeaflet
from app.kaufland_source_discovery import KauflandSourceDiscoveryError


def _family(*, active: bool = True, identity_sha256: str = "a" * 64) -> FreezeFamily:
    body = b"exact-store-leaflet"
    sha = hashlib.sha256(body).hexdigest()
    url = "https://leaflets.kaufland.com/DE_de_KDZ1_1503_D33/ar/1503"
    preflight = K2FamilyPreflight(
        source_identifier="DE_de_KDZ1_1503_D33",
        relation="current_main",
        store_bound=True,
        valid_from="2026-08-13",
        valid_to="2026-08-19",
        preview=False,
        active_at_collection=active,
        requested_url=url,
        final_url=url,
        content_type="text/html; charset=utf-8",
        byte_count=len(body),
        sha256=sha,
        redirects=(),
        freeze_key="kaufland/1503/2026-08-13_2026-08-19/DE_de_KDZ1_1503_D33",
        identity_sha256=identity_sha256,
    )
    raw = CapturedArtifact(
        role="leaflet-current_main-DE_de_KDZ1_1503_D33",
        requested_url=url,
        final_url=url,
        content_type="text/html; charset=utf-8",
        body=body,
        redirects=(),
    )
    return FreezeFamily(preflight=preflight, raw=raw)


def _bundle(
    *,
    revision: str = "b" * 40,
    common_body: bytes = b"context-v1",
    active: bool = True,
    identity_sha256: str = "a" * 64,
    skipped: tuple[K2SkippedLeaflet, ...] = (),
) -> FreezeBundle:
    common = CapturedArtifact(
        role="offer-overview",
        requested_url="https://filiale.kaufland.de/angebote/uebersicht.html",
        final_url="https://filiale.kaufland.de/angebote/uebersicht.html",
        content_type="text/html; charset=utf-8",
        body=common_body,
        redirects=(),
    )
    return FreezeBundle(
        git_revision=revision,
        collection_timestamp="2026-08-19T20:00:00+02:00",
        parser_input_contract_version="kaufland-k2-v1",
        common_sources=(common,),
        families=(_family(active=active, identity_sha256=identity_sha256),),
        skipped_leaflets=skipped,
    )


def test_authorization_identity_ignores_context_and_time_derived_state() -> None:
    skipped = (
        K2SkippedLeaflet(
            source_identifier="thematic",
            requested_url="https://leaflets.kaufland.com/thematic/ar/0",
            validity_label=None,
            preview=False,
            reason="not_exact_store_1503_bound",
        ),
    )
    planned = _bundle()
    captured = replace(
        _bundle(common_body=b"context-v2", active=False, skipped=skipped),
        collection_timestamp="2026-08-20T00:01:00+02:00",
    )

    assert authorization_identity_sha256(planned) == authorization_identity_sha256(captured)
    assert bundle_identity_sha256(planned) != bundle_identity_sha256(captured)


def test_authorization_identity_binds_revision_and_exact_family_identity() -> None:
    planned = _bundle()

    assert authorization_identity_sha256(planned) != authorization_identity_sha256(
        _bundle(revision="c" * 40)
    )
    assert authorization_identity_sha256(planned) != authorization_identity_sha256(
        _bundle(identity_sha256="d" * 64)
    )


def test_authorization_identity_rejects_raw_preflight_mismatch() -> None:
    bundle = _bundle()
    family = bundle.families[0]
    invalid = replace(
        bundle,
        families=(replace(family, raw=replace(family.raw, body=b"tampered")),),
    )

    with pytest.raises(KauflandSourceDiscoveryError) as exc_info:
        authorization_identity_sha256(invalid)

    assert exc_info.value.code == "EVIDENCE_IDENTITY_MISMATCH"
