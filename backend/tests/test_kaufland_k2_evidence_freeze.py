from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.kaufland_evidence_freeze import (
    CapturedArtifact,
    FreezeBundle,
    FreezeFamily,
    apply_freeze,
    bundle_identity_sha256,
    bundle_key,
    inspect_occupancy,
    validate_retained_root,
)
from app.kaufland_evidence_preflight import K2FamilyPreflight
from app.kaufland_source_discovery import KauflandSourceDiscoveryError


def _family(
    *,
    identifier: str,
    relation: str,
    valid_from: str,
    valid_to: str,
    body: bytes,
    preview: bool = False,
) -> FreezeFamily:
    url = f"https://leaflets.kaufland.com/{identifier}/ar/1503"
    sha = hashlib.sha256(body).hexdigest()
    preflight = K2FamilyPreflight(
        source_identifier=identifier,
        relation=relation,
        store_bound=True,
        valid_from=valid_from,
        valid_to=valid_to,
        preview=preview,
        active_at_collection=not preview,
        requested_url=url,
        final_url=url,
        content_type="text/html; charset=utf-8",
        byte_count=len(body),
        sha256=sha,
        redirects=(),
        freeze_key=f"kaufland/1503/{valid_from}_{valid_to}/{identifier}",
        identity_sha256="a" * 64,
    )
    return FreezeFamily(
        preflight=preflight,
        raw=CapturedArtifact(
            role=f"leaflet-{relation}-{identifier}",
            requested_url=url,
            final_url=url,
            content_type="text/html; charset=utf-8",
            body=body,
            redirects=(),
        ),
    )


def _bundle(*, revision: str = "b" * 40, timestamp: str = "2026-08-19T11:00:00+02:00") -> FreezeBundle:
    common = (
        CapturedArtifact(
            role="store-page",
            requested_url="https://filiale.kaufland.de/service/filiale/dortmund-aplerbeck-1503.html",
            final_url="https://filiale.kaufland.de/service/filiale/dortmund-aplerbeck-1503.html",
            content_type="text/html; charset=utf-8",
            body=b"store page 1503",
            redirects=(),
        ),
        CapturedArtifact(
            role="offer-overview",
            requested_url="https://filiale.kaufland.de/angebote/uebersicht.html",
            final_url="https://filiale.kaufland.de/angebote/uebersicht.html",
            content_type="text/html; charset=utf-8",
            body=b"offers for store 1503",
            redirects=(),
        ),
    )
    families = (
        _family(
            identifier="DE_de_KDZ1_1503_D33",
            relation="current_main",
            valid_from="2026-08-13",
            valid_to="2026-08-19",
            body=b"current-main",
        ),
        _family(
            identifier="DE_de_KDZ2_1503_D34-MoMi",
            relation="current_short",
            valid_from="2026-08-17",
            valid_to="2026-08-19",
            body=b"current-short",
        ),
        _family(
            identifier="DE_de_KDZ1_1503_D34",
            relation="preview_main",
            valid_from="2026-08-20",
            valid_to="2026-08-26",
            body=b"preview-main",
            preview=True,
        ),
        _family(
            identifier="DE_de_leaflet2_1503_D34-EL-Schule",
            relation="preview_overlap",
            valid_from="2026-08-20",
            valid_to="2026-09-02",
            body=b"preview-school",
            preview=True,
        ),
    )
    return FreezeBundle(
        git_revision=revision,
        collection_timestamp=timestamp,
        parser_input_contract_version="kaufland-k2-v1",
        common_sources=common,
        families=families,
        skipped_leaflets=(),
    )


def _target(root: Path, bundle: FreezeBundle) -> Path:
    return root.joinpath(*bundle_key(bundle).split("/"))


def test_bundle_identity_ignores_collection_timestamp_but_binds_revision() -> None:
    first = _bundle(timestamp="2026-08-19T11:00:00+02:00")
    second = _bundle(timestamp="2026-08-19T11:05:00+02:00")
    changed_revision = _bundle(revision="c" * 40)

    assert bundle_identity_sha256(first) == bundle_identity_sha256(second)
    assert bundle_identity_sha256(first) != bundle_identity_sha256(changed_revision)


def test_apply_is_create_once_then_identical_no_op(tmp_path: Path) -> None:
    bundle = _bundle()
    root = tmp_path / "retained"

    planned = inspect_occupancy(root, bundle)
    assert planned.action == "CREATE"

    created = apply_freeze(root, bundle)
    assert created.action == "CREATE"
    target = _target(root, bundle)
    assert not (target / "INCOMPLETE").exists()
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["bundle_identity_sha256"] == bundle_identity_sha256(bundle)
    assert manifest["production_database_write"] is False
    assert manifest["production_deploy"] is False
    assert len(list(target.glob("families/**/source.bin"))) == 4

    identical_later = _bundle(timestamp="2026-08-19T11:10:00+02:00")
    no_op = apply_freeze(root, identical_later)
    assert no_op.action == "NO_OP"


def test_non_identical_occupancy_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "retained"
    original = _bundle()
    apply_freeze(root, original)

    changed_families = list(_bundle().families)
    changed_families[-1] = _family(
        identifier="DE_de_leaflet2_1503_D34-EL-Schule",
        relation="preview_overlap",
        valid_from="2026-08-20",
        valid_to="2026-09-02",
        body=b"different-preview-school",
        preview=True,
    )
    changed = FreezeBundle(
        git_revision=original.git_revision,
        collection_timestamp=original.collection_timestamp,
        parser_input_contract_version=original.parser_input_contract_version,
        common_sources=original.common_sources,
        families=tuple(changed_families),
        skipped_leaflets=(),
    )

    with pytest.raises(KauflandSourceDiscoveryError) as exc_info:
        inspect_occupancy(root, changed)
    assert exc_info.value.code == "EVIDENCE_COLLISION"


def test_incomplete_marker_requires_manual_inspection(tmp_path: Path) -> None:
    bundle = _bundle()
    root = tmp_path / "retained"
    target = _target(root, bundle)
    target.mkdir(parents=True)
    (target / "INCOMPLETE").write_text("partial\n", encoding="utf-8")

    with pytest.raises(KauflandSourceDiscoveryError) as exc_info:
        inspect_occupancy(root, bundle)
    assert exc_info.value.code == "INCOMPLETE_EVIDENCE_PRESENT"


def test_retained_root_must_be_outside_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(KauflandSourceDiscoveryError) as exc_info:
        validate_retained_root(repo / "retained", repository_root=repo)
    assert exc_info.value.code == "RETAINED_ROOT_INSIDE_REPOSITORY"

    outside = validate_retained_root(tmp_path / "owner-retained", repository_root=repo)
    assert outside == (tmp_path / "owner-retained").resolve()


def test_raw_identity_mismatch_fails_before_write(tmp_path: Path) -> None:
    bundle = _bundle()
    bad = list(bundle.families)
    original = bad[0]
    bad[0] = FreezeFamily(
        preflight=original.preflight,
        raw=CapturedArtifact(
            role=original.raw.role,
            requested_url=original.raw.requested_url,
            final_url=original.raw.final_url,
            content_type=original.raw.content_type,
            body=b"tampered",
            redirects=(),
        ),
    )
    invalid = FreezeBundle(
        git_revision=bundle.git_revision,
        collection_timestamp=bundle.collection_timestamp,
        parser_input_contract_version=bundle.parser_input_contract_version,
        common_sources=bundle.common_sources,
        families=tuple(bad),
        skipped_leaflets=(),
    )

    with pytest.raises(KauflandSourceDiscoveryError) as exc_info:
        apply_freeze(tmp_path / "retained", invalid)
    assert exc_info.value.code == "EVIDENCE_IDENTITY_MISMATCH"
    assert not (tmp_path / "retained").exists()


def test_unsafe_source_identifier_cannot_become_retained_path(tmp_path: Path) -> None:
    bundle = _bundle()
    bad = list(bundle.families)
    original = bad[0]
    bad_preflight = K2FamilyPreflight(
        **{
            **original.preflight.__dict__,
            "source_identifier": "..",
        }
    )
    bad[0] = FreezeFamily(preflight=bad_preflight, raw=original.raw)
    invalid = FreezeBundle(
        git_revision=bundle.git_revision,
        collection_timestamp=bundle.collection_timestamp,
        parser_input_contract_version=bundle.parser_input_contract_version,
        common_sources=bundle.common_sources,
        families=tuple(bad),
        skipped_leaflets=(),
    )

    with pytest.raises(KauflandSourceDiscoveryError) as exc_info:
        inspect_occupancy(tmp_path / "retained", invalid)
    assert exc_info.value.code in {"UNSAFE_EVIDENCE_PATH", "EVIDENCE_IDENTITY_MISMATCH"}
