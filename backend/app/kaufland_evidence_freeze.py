from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
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
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY_MANIFEST_KEYS = (
    "schema_version",
    "contract_version",
    "git_revision",
    "store_id",
    "store_name",
    "address",
    "postcode_city",
    "parser_input_contract_version",
    "common_sources",
    "families",
    "skipped_leaflets",
)


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


def _target_dir_for_bundle_key(retained_root: Path, expected_bundle_key: str) -> Path:
    parts = expected_bundle_key.split("/")
    if len(parts) != 4 or parts[:3] != ["kaufland", STORE_ID, "k2"]:
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_COLLISION",
            "Retained K2 replay bundle key is not exact-store 1503 K2 evidence",
        )
    for index, part in enumerate(parts):
        _safe_component(part, label=f"bundle key component {index}")
    return retained_root.joinpath(*parts)


def _safe_relative_path(value: object) -> Path:
    if not isinstance(value, str):
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_COLLISION",
            "Retained artifact relative_path must be a string",
        )
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts:
        raise KauflandSourceDiscoveryError(
            "UNSAFE_EVIDENCE_PATH",
            "Retained artifact path must be a safe relative path",
        )
    for index, part in enumerate(pure.parts):
        _safe_component(part, label=f"retained artifact path component {index}")
    return Path(*pure.parts)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _retained_identity_payload(manifest: dict[str, object]) -> dict[str, object]:
    missing = [key for key in _IDENTITY_MANIFEST_KEYS if key not in manifest]
    if missing:
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_COLLISION",
            f"Retained K2 manifest is missing identity fields: {', '.join(missing)}",
        )
    return {key: manifest[key] for key in _IDENTITY_MANIFEST_KEYS}


def verify_retained_bundle(
    retained_root: Path,
    *,
    expected_bundle_key: str,
    expected_git_revision: str,
    expected_parser_input_contract_version: str,
    expected_bundle_identity_sha256: str,
) -> FreezeDecision:
    if not _SHA256_RE.fullmatch(expected_bundle_identity_sha256):
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_COLLISION",
            "Expected retained K2 bundle identity must be a lowercase SHA-256",
        )
    target = _target_dir_for_bundle_key(retained_root, expected_bundle_key)
    if target.is_symlink() or not target.exists() or not target.is_dir():
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_COLLISION",
            "Retained K2 replay target is missing, symlinked or not a directory",
        )
    incomplete = target / INCOMPLETE_MARKER
    if incomplete.exists() or incomplete.is_symlink():
        raise KauflandSourceDiscoveryError(
            "INCOMPLETE_EVIDENCE_PRESENT",
            "Retained K2 target contains an incomplete capture marker; inspect manually",
        )
    manifest_path = target / MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_COLLISION",
            "Retained K2 replay target lacks a regular immutable manifest",
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_COLLISION",
            "Retained K2 manifest cannot be read deterministically",
        ) from exc
    if not isinstance(manifest, dict):
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_COLLISION",
            "Retained K2 manifest root must be an object",
        )

    exact_fields = {
        "schema_version": FREEZE_SCHEMA_VERSION,
        "contract_version": FREEZE_CONTRACT_VERSION,
        "git_revision": expected_git_revision,
        "store_id": STORE_ID,
        "store_name": STORE_NAME,
        "address": STORE_ADDRESS,
        "postcode_city": STORE_POSTCODE_CITY,
        "parser_input_contract_version": expected_parser_input_contract_version,
        "bundle_key": expected_bundle_key,
        "bundle_identity_sha256": expected_bundle_identity_sha256,
        "retained_evidence": True,
        "raw_material_retained": True,
        "production_database_write": False,
        "review_write": False,
        "production_publish": False,
        "production_deploy": False,
        "scheduler_change": False,
        "systemd_change": False,
    }
    for key, expected in exact_fields.items():
        if manifest.get(key) != expected:
            raise KauflandSourceDiscoveryError(
                "EVIDENCE_COLLISION",
                f"Retained K2 manifest mismatch for {key}",
            )

    identity_payload = _retained_identity_payload(manifest)
    if _stable_sha(identity_payload) != expected_bundle_identity_sha256:
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_COLLISION",
            "Retained K2 manifest identity payload does not match the expected bundle identity",
        )

    common = manifest.get("common_sources")
    families = manifest.get("families")
    if not isinstance(common, list) or not isinstance(families, list) or not families:
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_COLLISION",
            "Retained K2 manifest artifact/family structure is invalid",
        )

    artifact_records: list[dict[str, object]] = []
    for item in common:
        if not isinstance(item, dict):
            raise KauflandSourceDiscoveryError(
                "EVIDENCE_COLLISION",
                "Retained K2 common artifact record is invalid",
            )
        artifact_records.append(item)
    for family in families:
        if not isinstance(family, dict):
            raise KauflandSourceDiscoveryError(
                "EVIDENCE_COLLISION",
                "Retained K2 family record is invalid",
            )
        preflight = family.get("preflight")
        raw = family.get("raw")
        if not isinstance(preflight, dict) or preflight.get("store_bound") is not True or not isinstance(raw, dict):
            raise KauflandSourceDiscoveryError(
                "EVIDENCE_COLLISION",
                "Retained K2 family is not exact-store-bound complete evidence",
            )
        if (
            raw.get("requested_url") != preflight.get("requested_url")
            or raw.get("final_url") != preflight.get("final_url")
            or raw.get("content_type") != preflight.get("content_type")
            or raw.get("byte_count") != preflight.get("byte_count")
            or raw.get("sha256") != preflight.get("sha256")
            or raw.get("redirects") != preflight.get("redirects")
        ):
            raise KauflandSourceDiscoveryError(
                "EVIDENCE_COLLISION",
                "Retained K2 family raw metadata does not match its frozen preflight identity",
            )
        artifact_records.append(raw)

    expected_files = {MANIFEST_NAME}
    expected_dirs = {"."}
    for item in artifact_records:
        relative = _safe_relative_path(item.get("relative_path"))
        relative_text = relative.as_posix()
        if relative_text in expected_files:
            raise KauflandSourceDiscoveryError(
                "EVIDENCE_COLLISION",
                f"Retained K2 manifest contains duplicate artifact path {relative_text}",
            )
        expected_files.add(relative_text)
        parent = PurePosixPath(relative_text).parent
        while str(parent) not in {"", "."}:
            expected_dirs.add(str(parent))
            parent = parent.parent

        expected_bytes = item.get("byte_count")
        expected_sha = item.get("sha256")
        if (
            not isinstance(expected_bytes, int)
            or expected_bytes < 0
            or not isinstance(expected_sha, str)
            or not _SHA256_RE.fullmatch(expected_sha)
        ):
            raise KauflandSourceDiscoveryError(
                "EVIDENCE_COLLISION",
                f"Retained K2 artifact metadata is invalid for {relative_text}",
            )
        path = target / relative
        if path.is_symlink() or not path.is_file():
            raise KauflandSourceDiscoveryError(
                "EVIDENCE_COLLISION",
                f"Retained K2 artifact is missing, symlinked or non-regular: {relative_text}",
            )
        stat_result = path.stat()
        if stat_result.st_size != expected_bytes or _sha256_file(path) != expected_sha:
            raise KauflandSourceDiscoveryError(
                "RETAINED_ARTIFACT_MISMATCH",
                f"Retained K2 artifact bytes do not match manifest: {relative_text}",
            )

    actual_files: set[str] = set()
    actual_dirs: set[str] = {"."}
    for root, dirs, files in os.walk(target, topdown=True, followlinks=False):
        root_path = Path(root)
        for name in dirs:
            path = root_path / name
            if path.is_symlink():
                raise KauflandSourceDiscoveryError(
                    "EVIDENCE_COLLISION",
                    f"Retained K2 tree contains a symlink directory: {path.relative_to(target).as_posix()}",
                )
            actual_dirs.add(path.relative_to(target).as_posix())
        for name in files:
            path = root_path / name
            if path.is_symlink():
                raise KauflandSourceDiscoveryError(
                    "EVIDENCE_COLLISION",
                    f"Retained K2 tree contains a symlink file: {path.relative_to(target).as_posix()}",
                )
            actual_files.add(path.relative_to(target).as_posix())
    if actual_files != expected_files or actual_dirs != expected_dirs:
        raise KauflandSourceDiscoveryError(
            "EVIDENCE_COLLISION",
            "Retained K2 tree contains missing or extra files/directories",
        )

    return FreezeDecision(
        "NO_OP",
        expected_bundle_key,
        expected_bundle_identity_sha256,
        len(artifact_records),
        len(families),
    )


def inspect_occupancy(retained_root: Path, bundle: FreezeBundle) -> FreezeDecision:
    target = _target_dir(retained_root, bundle)
    identity = bundle_identity_sha256(bundle)
    artifact_count = len(bundle.common_sources) + len(bundle.families)
    if not target.exists():
        return FreezeDecision("CREATE", bundle_key(bundle), identity, artifact_count, len(bundle.families))
    return verify_retained_bundle(
        retained_root,
        expected_bundle_key=bundle_key(bundle),
        expected_git_revision=bundle.git_revision,
        expected_parser_input_contract_version=bundle.parser_input_contract_version,
        expected_bundle_identity_sha256=identity,
    )


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
