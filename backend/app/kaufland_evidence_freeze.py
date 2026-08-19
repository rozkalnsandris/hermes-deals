from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from app.kaufland_evidence_preflight import K2FamilyPreflight, K2SkippedLeaflet
from app.kaufland_source_discovery import (
    STORE_ADDRESS,
    STORE_ID,
    STORE_NAME,
    STORE_POSTCODE_CITY,
    KauflandSourceDiscoveryError,
    RedirectHop,
)

FREEZE_SCHEMA_VERSION = 1
FREEZE_CONTRACT_VERSION = "kaufland-k2-retained-freeze-v1"
INCOMPLETE_MARKER = "INCOMPLETE"
MANIFEST_NAME = "manifest.json"
_SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class CapturedArtifact:
    role: str
    requested_url: str
    final_url: str
    content_type: str
    body: bytes
    redirects: tuple[RedirectHop, ...]

    @property
    def byte_count(self) -> int:
        return len(self.body)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


@dataclass(frozen=True)
class FreezeFamily:
    preflight: K2FamilyPreflight
    raw: CapturedArtifact


@dataclass(frozen=True)
class FreezeBundle:
    git_revision: str
    collection_timestamp: str
    parser_input_contract_version: str
    common_sources: tuple[CapturedArtifact, ...]
    families: tuple[FreezeFamily, ...]
    skipped_leaflets: tuple[K2SkippedLeaflet, ...]


@dataclass(frozen=True)
class FreezeDecision:
    action: str
    bundle_key: str
    bundle_identity_sha256: str
    artifact_count: int
    family_count: int


def _stable_sha(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _redirects_payload(redirects: Iterable[RedirectHop]) -> list[dict[str, object]]:
    return [asdict(item) for item in redirects]


def _safe_component(value: str, *, label: str) -> str:
    if value in {"", ".", ".."} or not _SAFE_COMPONENT_RE.fullmatch(value):
        raise KauflandSourceDiscoveryError(
            "UNSAFE_EVIDENCE_PATH",
            f"Unsafe {label} path component in retained evidence identity",
        )
    return value


def _validate_family_raw(family: FreezeFamily) -> None:
    preflight = family.preflight
    raw = family.raw
    if not preflight.store_bound:
        raise KauflandSourceDiscoveryError(
            "STORE_BINDING_NOT_PROVEN",
            "Retained family is not exact-store bound",
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
            "Retained family raw bytes/metadata do not match the K2 preflight identity",
        )


def _artifact_identity_payload(artifact: CapturedArtifact, *, relative_path: str) -> dict[str, object]:
    return {
        "role": artifact.role,
        "relative_path": relative_path,
        "requested_url": artifact.requested_url,
        "final_url": artifact.final_url,
        "content_type": artifact.content_type,
        "byte_count": artifact.byte_count,
        "sha256": artifact.sha256,
        "redirects": _redirects_payload(artifact.redirects),
    }


def _family_relative_path(family: FreezeFamily) -> str:
    _validate_family_raw(family)
    validity = _safe_component(
        f"{family.preflight.valid_from}_{family.preflight.valid_to}",
        label="validity",
    )
    relation = _safe_component(family.preflight.relation, label="relation")
    identifier = _safe_component(
        family.preflight.source_identifier,
        label="source identifier",
    )
    return f"families/{validity}/{relation}/{identifier}/source.bin"


def _bundle_identity_payload(bundle: FreezeBundle) -> dict[str, object]:
    common = [
        _artifact_identity_payload(item, relative_path=f"common/{_safe_component(item.role, label='role')}.bin")
        for item in sorted(bundle.common_sources, key=lambda item: item.role)
    ]
    families: list[dict[str, object]] = []
    for item in sorted(
        bundle.families,
        key=lambda value: (
            value.preflight.valid_from,
            value.preflight.valid_to,
            value.preflight.source_identifier,
        ),
    ):
        families.append(
            {
                "preflight": asdict(item.preflight),
                "raw": _artifact_identity_payload(
                    item.raw,
                    relative_path=_family_relative_path(item),
                ),
            }
        )
    return {
        "schema_version": FREEZE_SCHEMA_VERSION,
        "contract_version": FREEZE_CONTRACT_VERSION,
        "git_revision": bundle.git_revision,
        "store_id": STORE_ID,
        "store_name": STORE_NAME,
        "address": STORE_ADDRESS,
        "postcode_city": STORE_POSTCODE_CITY,
        "parser_input_contract_version": bundle.parser_input_contract_version,
        "common_sources": common,
        "families": families,
        "skipped_leaflets": [asdict(item) for item in bundle.skipped_leaflets],
    }


def bundle_key(bundle: FreezeBundle) -> str:
    if not bundle.families:
        raise KauflandSourceDiscoveryError(
            "INSUFFICIENT_K2_FAMILIES",
            "Retained freeze bundle contains no exact-store families",
        )
    starts = [item.preflight.valid_from for item in bundle.families]
    ends = [item.preflight.valid_to for item in bundle.families]
    validity = _safe_component(f"{min(starts)}_{max(ends)}", label="bundle validity")
    return f"kaufland/{STORE_ID}/k2/{validity}"


def bundle_identity_sha256(bundle: FreezeBundle) -> str:
    return _stable_sha(_bundle_identity_payload(bundle))


def _manifest_payload(bundle: FreezeBundle) -> dict[str, object]:
    identity_payload = _bundle_identity_payload(bundle)
    return {
        **identity_payload,
        "collection_timestamp": bundle.collection_timestamp,
        "bundle_key": bundle_key(bundle),
        "bundle_identity_sha256": _stable_sha(identity_payload),
        "retained_evidence": True,
        "raw_material_retained": True,
        "production_database_write": False,
        "review_write": False,
        "production_publish": False,
        "production_deploy": False,
        "scheduler_change": False,
        "systemd_change": False,
    }


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_retained_root(retained_root: Path, *, repository_root: Path) -> Path:
    repo = repository_root.resolve()
    root = retained_root.expanduser().resolve(strict=False)
    if _is_relative_to(root, repo):
        raise KauflandSourceDiscoveryError(
            "RETAINED_ROOT_INSIDE_REPOSITORY",
            "Kaufland raw retained evidence must not be stored inside the Git repository",
        )
    return root


def _target_dir(retained_root: Path, bundle: FreezeBundle) -> Path:
    return retained_root.joinpath(*bundle_key(bundle).split("/"))


def inspect_occupancy(retained_root: Path, bundle: FreezeBundle) -> FreezeDecision:
    target = _target_dir(retained_root, bundle)
    identity = bundle_identity_sha256(bundle)
    artifact_count = len(bundle.common_sources) + len(bundle.families)
    if not target.exists():
        return FreezeDecision("CREATE", bundle_key(bundle), identity, artifact_count, len(bundle.families))
    if not target.is_dir():
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_COLLISION",
            "Retained K2 target is occupied by a non-directory entry",
        )
    if (target / INCOMPLETE_MARKER).exists():
        raise KauflandSourceDiscoveryError(
            "INCOMPLETE_EVIDENCE_PRESENT",
            "Retained K2 target contains an incomplete capture marker; inspect manually",
        )
    manifest_path = target / MANIFEST_NAME
    if not manifest_path.is_file():
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_COLLISION",
            "Retained K2 target exists without a complete manifest",
        )
    try:
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_COLLISION",
            "Retained K2 manifest cannot be read deterministically",
        ) from exc
    if existing.get("bundle_identity_sha256") != identity:
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_COLLISION",
            "Retained K2 bundle key is occupied by non-identical evidence",
        )
    return FreezeDecision("NO_OP", bundle_key(bundle), identity, artifact_count, len(bundle.families))


def _mkdir_exclusive(path: Path) -> None:
    path.mkdir(mode=0o700, parents=False, exist_ok=False)


def _write_bytes_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)


def _write_text_exclusive(path: Path, text: str) -> None:
    _write_bytes_exclusive(path, text.encode("utf-8"))


def _verify_file(path: Path, expected_sha256: str, expected_bytes: int) -> None:
    data = path.read_bytes()
    if len(data) != expected_bytes or hashlib.sha256(data).hexdigest() != expected_sha256:
        raise KauflandSourceDiscoveryError(
            "POST_WRITE_VERIFICATION_FAILED",
            f"Retained evidence verification failed for {path.name}",
        )


def apply_freeze(retained_root: Path, bundle: FreezeBundle) -> FreezeDecision:
    decision = inspect_occupancy(retained_root, bundle)
    if decision.action == "NO_OP":
        return decision

    target = _target_dir(retained_root, bundle)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        _mkdir_exclusive(target)
    except FileExistsError as exc:
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_COLLISION",
            "Retained K2 target became occupied before create-once write",
        ) from exc

    marker = target / INCOMPLETE_MARKER
    _write_text_exclusive(marker, "Kaufland K2 retained freeze incomplete\n")

    try:
        for artifact in sorted(bundle.common_sources, key=lambda item: item.role):
            relative = Path("common") / f"{_safe_component(artifact.role, label='role')}.bin"
            destination = target / relative
            _write_bytes_exclusive(destination, artifact.body)
            _verify_file(destination, artifact.sha256, artifact.byte_count)

        for family in bundle.families:
            relative = Path(_family_relative_path(family))
            destination = target / relative
            _write_bytes_exclusive(destination, family.raw.body)
            _verify_file(destination, family.raw.sha256, family.raw.byte_count)

        manifest = _manifest_payload(bundle)
        manifest_text = json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
        manifest_path = target / MANIFEST_NAME
        _write_text_exclusive(manifest_path, manifest_text)
        manifest_bytes = manifest_text.encode("utf-8")
        _verify_file(
            manifest_path,
            hashlib.sha256(manifest_bytes).hexdigest(),
            len(manifest_bytes),
        )
        marker.unlink()
    except Exception:
        # The marker deliberately remains on any failure. A later run must fail closed
        # and require owner inspection instead of overwriting partial evidence.
        raise

    return FreezeDecision(
        "CREATE",
        bundle_key(bundle),
        bundle_identity_sha256(bundle),
        len(bundle.common_sources) + len(bundle.families),
        len(bundle.families),
    )
