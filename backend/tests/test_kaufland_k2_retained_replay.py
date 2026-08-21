from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.kaufland_evidence_freeze import (
    CapturedArtifact,
    FreezeBundle,
    FreezeDecision,
    FreezeFamily,
    apply_freeze,
    bundle_identity_sha256,
    bundle_key,
    verify_retained_bundle,
)
from app.kaufland_evidence_preflight import K2FamilyPreflight
from app.kaufland_source_discovery import KauflandSourceDiscoveryError

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "kaufland_k2_evidence_freeze.py"


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
        identity_sha256=hashlib.sha256(f"{relation}:{sha}".encode()).hexdigest(),
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


def _bundle() -> FreezeBundle:
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
        git_revision="b" * 40,
        collection_timestamp="2026-08-19T11:00:00+02:00",
        parser_input_contract_version="kaufland-k2-v1",
        common_sources=common,
        families=families,
        skipped_leaflets=(),
    )


def _target(root: Path, bundle: FreezeBundle) -> Path:
    return root.joinpath(*bundle_key(bundle).split("/"))


def _verify(root: Path, bundle: FreezeBundle) -> FreezeDecision:
    return verify_retained_bundle(
        root,
        expected_bundle_key=bundle_key(bundle),
        expected_git_revision=bundle.git_revision,
        expected_parser_input_contract_version=bundle.parser_input_contract_version,
        expected_bundle_identity_sha256=bundle_identity_sha256(bundle),
    )


def _tree_snapshot(target: Path) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for path in [target, *sorted(target.rglob("*"))]:
        stat_result = path.stat()
        rel = "." if path == target else path.relative_to(target).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        rows.append(
            (
                rel,
                stat_result.st_ino,
                stat_result.st_size,
                stat_result.st_mode,
                stat_result.st_mtime_ns,
                stat_result.st_ctime_ns,
                digest,
            )
        )
    return rows


def test_retained_replay_verifier_rehashes_and_is_metadata_immutable(tmp_path: Path) -> None:
    bundle = _bundle()
    root = tmp_path / "retained"
    apply_freeze(root, bundle)
    target = _target(root, bundle)
    before = _tree_snapshot(target)

    decision = _verify(root, bundle)

    assert decision.action == "NO_OP"
    assert decision.bundle_identity_sha256 == bundle_identity_sha256(bundle)
    assert decision.artifact_count == 6
    assert decision.family_count == 4
    assert _tree_snapshot(target) == before


def test_retained_replay_verifier_rejects_corrupt_artifact_bytes(tmp_path: Path) -> None:
    bundle = _bundle()
    root = tmp_path / "retained"
    apply_freeze(root, bundle)
    target = _target(root, bundle)
    artifact = next(target.glob("families/**/source.bin"))
    artifact.write_bytes(b"corrupt")

    with pytest.raises(KauflandSourceDiscoveryError) as exc_info:
        _verify(root, bundle)

    assert exc_info.value.code == "RETAINED_ARTIFACT_MISMATCH"


def test_retained_replay_verifier_rejects_manifest_identity_mismatch(tmp_path: Path) -> None:
    bundle = _bundle()
    root = tmp_path / "retained"
    apply_freeze(root, bundle)
    manifest_path = _target(root, bundle) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["parser_input_contract_version"] = "tampered-contract"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(KauflandSourceDiscoveryError) as exc_info:
        _verify(root, bundle)

    assert exc_info.value.code == "EVIDENCE_COLLISION"


def test_retained_replay_verifier_rejects_incomplete_and_extra_nodes(tmp_path: Path) -> None:
    bundle = _bundle()
    root = tmp_path / "retained"
    apply_freeze(root, bundle)
    target = _target(root, bundle)
    marker = target / "INCOMPLETE"
    marker.write_text("partial\n", encoding="utf-8")

    with pytest.raises(KauflandSourceDiscoveryError) as exc_info:
        _verify(root, bundle)
    assert exc_info.value.code == "INCOMPLETE_EVIDENCE_PRESENT"

    marker.unlink()
    (target / "extra.bin").write_bytes(b"unexpected")
    with pytest.raises(KauflandSourceDiscoveryError) as exc_info:
        _verify(root, bundle)
    assert exc_info.value.code == "EVIDENCE_COLLISION"


def test_retained_replay_verifier_rejects_symlink(tmp_path: Path) -> None:
    bundle = _bundle()
    root = tmp_path / "retained"
    apply_freeze(root, bundle)
    target = _target(root, bundle)
    os.symlink(target / "manifest.json", target / "unexpected-link")

    with pytest.raises(KauflandSourceDiscoveryError) as exc_info:
        _verify(root, bundle)

    assert exc_info.value.code == "EVIDENCE_COLLISION"


def _load_cli_module():
    spec = importlib.util.spec_from_file_location("kaufland_k2_evidence_freeze_replay_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_existing_bundle_apply_no_op_is_offline(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    module = _load_cli_module()
    retained_root = (tmp_path / "retained").resolve()
    decision = FreezeDecision(
        "NO_OP",
        "kaufland/1503/k2/2026-08-13_2026-09-02",
        "a" * 64,
        6,
        4,
    )
    executor_revision = "c" * 40
    retained_revision = "b" * 40
    replay_identity = module._replay_authorization_identity_sha256(
        executor_revision=executor_revision,
        retained_root=retained_root,
        decision=decision,
        retained_git_revision=retained_revision,
        parser_input_contract_version="kaufland-k2-v1",
    )
    args = SimpleNamespace(
        retained_root=retained_root,
        expected_revision=executor_revision,
        expected_authorization_identity_sha256=None,
        expected_bundle_identity_sha256=None,
        replay_existing_bundle_key=decision.bundle_key,
        expected_retained_bundle_identity_sha256=decision.bundle_identity_sha256,
        expected_retained_git_revision=retained_revision,
        expected_retained_parser_input_contract_version="kaufland-k2-v1",
        expected_replay_authorization_identity_sha256=replay_identity,
        apply=True,
        authorization_token=module.AUTHORIZATION_TOKEN,
    )
    monkeypatch.setattr(module, "parse_args", lambda: args)
    monkeypatch.setattr(module, "_verify_checkout", lambda expected: None)
    monkeypatch.setattr(
        module,
        "validate_retained_root",
        lambda root, repository_root: retained_root,
    )
    monkeypatch.setattr(module, "verify_retained_bundle", lambda *a, **kw: decision)

    class NetworkForbidden:
        def __init__(self, *args, **kwargs):
            raise AssertionError("replay path must not construct httpx.Client")

    monkeypatch.setattr(module.httpx, "Client", NetworkForbidden)

    assert module.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "APPLY"
    assert payload["action"] == "NO_OP"
    assert payload["replay_authorization_identity_sha256"] == replay_identity
    assert payload["bundle_identity_sha256"] == decision.bundle_identity_sha256
    for key in (
        "retained_evidence_write",
        "raw_material_retained",
        "corpus_write",
        "production_database_write",
        "review_write",
        "production_publish",
        "production_deploy",
        "scheduler_change",
        "systemd_change",
    ):
        assert payload[key] is False


def test_create_plan_still_requires_live_client(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    module = _load_cli_module()
    args = SimpleNamespace(
        retained_root=tmp_path / "retained",
        expected_revision="c" * 40,
        expected_authorization_identity_sha256=None,
        expected_bundle_identity_sha256=None,
        replay_existing_bundle_key=None,
        expected_retained_bundle_identity_sha256=None,
        expected_retained_git_revision=None,
        expected_retained_parser_input_contract_version=None,
        expected_replay_authorization_identity_sha256=None,
        apply=False,
        authorization_token=None,
    )
    monkeypatch.setattr(module, "parse_args", lambda: args)
    monkeypatch.setattr(module, "_verify_checkout", lambda expected: None)
    monkeypatch.setattr(
        module,
        "validate_retained_root",
        lambda root, repository_root: root.resolve(),
    )

    class LiveClientRequired:
        def __init__(self, *args, **kwargs):
            raise AssertionError("live client required for CREATE/normal PLAN")

    monkeypatch.setattr(module.httpx, "Client", LiveClientRequired)

    with pytest.raises(AssertionError, match="live client required"):
        module.main()


def test_replay_authorization_identity_binds_fixed_revision_and_retained_bundle(tmp_path: Path) -> None:
    module = _load_cli_module()
    decision = FreezeDecision("NO_OP", "kaufland/1503/k2/window", "a" * 64, 6, 4)
    base = module._replay_authorization_identity_sha256(
        executor_revision="c" * 40,
        retained_root=tmp_path.resolve(),
        decision=decision,
        retained_git_revision="b" * 40,
        parser_input_contract_version="kaufland-k2-v1",
    )
    changed_executor = module._replay_authorization_identity_sha256(
        executor_revision="d" * 40,
        retained_root=tmp_path.resolve(),
        decision=decision,
        retained_git_revision="b" * 40,
        parser_input_contract_version="kaufland-k2-v1",
    )
    changed_bundle = module._replay_authorization_identity_sha256(
        executor_revision="c" * 40,
        retained_root=tmp_path.resolve(),
        decision=FreezeDecision("NO_OP", decision.bundle_key, "e" * 64, 6, 4),
        retained_git_revision="b" * 40,
        parser_input_contract_version="kaufland-k2-v1",
    )

    assert base != changed_executor
    assert base != changed_bundle
