from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import os
import platform
from pathlib import Path
import re
import sys
from typing import Any
from uuid import UUID


PARSER_CONTRACT_VERSION = "edeka-v1"
PARSER_PATH = "backend/app/parsers/edeka.py"
PARSER_FAILURE_SCHEMA_VERSION = 1
PARSER_FAILURE_STRATEGY = "edeka_patzer_parser_failure_v1"
PARSER_FAILURE_CONTENT_TYPE = (
    "application/vnd.hermes-deals.edeka-parser-failure+json"
)
PARSER_FAILURE_RETENTION_MAX_MANIFESTS = 20
_GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40}$")
_EXPECTED_SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
_EXPECTED_PUBLIC_MARKET_ID = "071897"
_EXPECTED_INTERNAL_MARKET_ID = "587881"
_EXPECTED_STORE_NAME = "EDEKA Patzer"
_EXPECTED_SCOPE = "family_primary_edeka"
_FAILURE_GLOB = "*-071897-parser-failure-manifest-*.json"


@dataclass(frozen=True)
class EdekaParserExecutionIdentity:
    source_registered_commit: str
    source_parser_blob_sha: str
    python_implementation: str
    python_version: str


@dataclass(frozen=True)
class EdekaRawSourceEvidence:
    path: Path
    sha256: str
    content_bytes: int


def _stable_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_immutable(path: Path, value: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != value:
            raise ValueError(
                f"Refusing to replace immutable EDEKA failure evidence: {path}"
            )


def _full_git_object(value: object, label: str) -> str:
    if not isinstance(value, str) or not _GIT_OBJECT_RE.fullmatch(value):
        raise ValueError(f"EDEKA parser identity {label} requires a full Git SHA")
    return value


def _runtime_python_identity() -> tuple[str, str]:
    implementation = str(sys.implementation.name)
    version = platform.python_version()
    if not implementation or any(char.isspace() for char in implementation):
        raise ValueError("EDEKA parser Python implementation is invalid")
    if not version or any(char.isspace() for char in version):
        raise ValueError("EDEKA parser Python version is invalid")
    return implementation, version


def parser_identity_from_environment() -> EdekaParserExecutionIdentity | None:
    commit = os.environ.get("EDEKA_SOURCE_REGISTERED_COMMIT")
    blob = os.environ.get("EDEKA_SOURCE_PARSER_BLOB_SHA")
    if commit is None and blob is None:
        return None
    if commit is None or blob is None:
        raise ValueError("EDEKA parser identity environment is incomplete")
    implementation, version = _runtime_python_identity()
    return EdekaParserExecutionIdentity(
        source_registered_commit=_full_git_object(commit, "source_registered_commit"),
        source_parser_blob_sha=_full_git_object(blob, "source_parser_blob_sha"),
        python_implementation=implementation,
        python_version=version,
    )


def validate_parser_identity(
    identity: EdekaParserExecutionIdentity,
) -> EdekaParserExecutionIdentity:
    commit = _full_git_object(
        identity.source_registered_commit,
        "source_registered_commit",
    )
    blob = _full_git_object(identity.source_parser_blob_sha, "source_parser_blob_sha")
    implementation = str(identity.python_implementation)
    version = str(identity.python_version)
    if not implementation or any(char.isspace() for char in implementation):
        raise ValueError("EDEKA parser Python implementation is invalid")
    if not version or any(char.isspace() for char in version):
        raise ValueError("EDEKA parser Python version is invalid")
    return EdekaParserExecutionIdentity(
        source_registered_commit=commit,
        source_parser_blob_sha=blob,
        python_implementation=implementation,
        python_version=version,
    )


def retain_raw_source(
    raw_snapshot_dir: Path,
    *,
    public_market_id: str,
    content: bytes,
) -> EdekaRawSourceEvidence:
    if public_market_id != _EXPECTED_PUBLIC_MARKET_ID:
        raise ValueError("EDEKA retained source public market ID mismatch")
    if not content:
        raise ValueError("EDEKA retained source is empty")
    root = raw_snapshot_dir.expanduser().resolve() / "edeka"
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("EDEKA retained source root is unsafe")
    digest = sha256(content).hexdigest()
    path = root / f"{public_market_id}-offers-{digest}.html"
    _write_immutable(path, content)
    return EdekaRawSourceEvidence(
        path=path,
        sha256=digest,
        content_bytes=len(content),
    )


def write_parser_failure_manifest(
    raw_snapshot_dir: Path,
    *,
    snapshot_id: object,
    collected_at: datetime,
    source_chain: str,
    scope: str,
    public_market_id: str,
    internal_market_id: str,
    store_name: str,
    source_url: str,
    final_url: str,
    raw: EdekaRawSourceEvidence,
    raw_content_type: str | None,
    http_status: int,
    elapsed_ms: int,
    identity: EdekaParserExecutionIdentity,
    error: BaseException,
) -> tuple[Path, str]:
    identity = validate_parser_identity(identity)
    expected = {
        "source_chain": (source_chain, "edeka"),
        "scope": (scope, _EXPECTED_SCOPE),
        "public_market_id": (public_market_id, _EXPECTED_PUBLIC_MARKET_ID),
        "internal_market_id": (internal_market_id, _EXPECTED_INTERNAL_MARKET_ID),
        "store_name": (store_name, _EXPECTED_STORE_NAME),
        "source_url": (source_url, _EXPECTED_SOURCE_URL),
        "final_url": (final_url, _EXPECTED_SOURCE_URL),
    }
    for label, (actual, wanted) in expected.items():
        if actual != wanted:
            raise ValueError(f"EDEKA parser failure {label} mismatch")
    if collected_at.tzinfo is None or collected_at.utcoffset() is None:
        raise ValueError("EDEKA parser failure collected_at must be timezone-aware")
    raw_root = raw_snapshot_dir.expanduser().resolve() / "edeka"
    raw_path = raw.path.expanduser().resolve()
    if raw_path.parent != raw_root:
        raise ValueError("EDEKA parser failure raw path escaped evidence root")
    raw_bytes = raw_path.read_bytes()
    if len(raw_bytes) != raw.content_bytes:
        raise ValueError("EDEKA parser failure raw byte count mismatch")
    if sha256(raw_bytes).hexdigest() != raw.sha256:
        raise ValueError("EDEKA parser failure raw SHA mismatch")

    bounded_error = f"{type(error).__name__}: {error}"[:2000]
    manifest = {
        "schema_version": PARSER_FAILURE_SCHEMA_VERSION,
        "strategy": PARSER_FAILURE_STRATEGY,
        "content_type": PARSER_FAILURE_CONTENT_TYPE,
        "outcome": "parser_failure",
        "snapshot_id": str(snapshot_id),
        "source_chain": source_chain,
        "scope": scope,
        "public_market_id": public_market_id,
        "internal_market_id": internal_market_id,
        "store_name": store_name,
        "source_url": source_url,
        "final_url": final_url,
        "collected_at": collected_at.isoformat(),
        "http_status": int(http_status),
        "elapsed_ms": int(elapsed_ms),
        "raw_html_path": str(raw_path),
        "raw_html_sha256": raw.sha256,
        "raw_content_type": raw_content_type,
        "raw_content_bytes": raw.content_bytes,
        "parser_contract_version": PARSER_CONTRACT_VERSION,
        "parser_path": PARSER_PATH,
        "source_registered_commit": identity.source_registered_commit,
        "source_parser_blob_sha": identity.source_parser_blob_sha,
        "python_implementation": identity.python_implementation,
        "python_version": identity.python_version,
        "error_type": type(error).__name__,
        "error": bounded_error,
        "accepted_campaign": False,
        "retention_policy": "operator_explicit_keep_latest_v1",
        "retention_max_failure_manifests": PARSER_FAILURE_RETENTION_MAX_MANIFESTS,
    }
    data = _stable_json_bytes(manifest)
    digest = sha256(data).hexdigest()
    stamp = collected_at.strftime("%Y%m%dT%H%M%SZ")
    path = raw_root / (
        f"{stamp}-{public_market_id}-parser-failure-manifest-{digest[:12]}.json"
    )
    _write_immutable(path, data)
    return path, digest


def read_parser_failure_manifest(
    manifest_path: Path,
    expected_sha256: str,
) -> dict[str, Any]:
    data = manifest_path.read_bytes()
    if sha256(data).hexdigest() != expected_sha256:
        raise ValueError("EDEKA parser failure manifest SHA mismatch")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("EDEKA parser failure manifest must be an object")
    expected = {
        "schema_version": PARSER_FAILURE_SCHEMA_VERSION,
        "strategy": PARSER_FAILURE_STRATEGY,
        "content_type": PARSER_FAILURE_CONTENT_TYPE,
        "outcome": "parser_failure",
        "source_chain": "edeka",
        "scope": _EXPECTED_SCOPE,
        "public_market_id": _EXPECTED_PUBLIC_MARKET_ID,
        "internal_market_id": _EXPECTED_INTERNAL_MARKET_ID,
        "store_name": _EXPECTED_STORE_NAME,
        "source_url": _EXPECTED_SOURCE_URL,
        "final_url": _EXPECTED_SOURCE_URL,
        "parser_contract_version": PARSER_CONTRACT_VERSION,
        "parser_path": PARSER_PATH,
        "accepted_campaign": False,
    }
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            raise ValueError(f"EDEKA parser failure manifest {key} mismatch")
    _full_git_object(value.get("source_registered_commit"), "source_registered_commit")
    _full_git_object(value.get("source_parser_blob_sha"), "source_parser_blob_sha")
    return value


def replay_parser_failure_offline(
    manifest_path: Path,
    expected_sha256: str,
    *,
    derivation_registered_commit: str,
    derivation_parser_blob_sha: str,
) -> dict[str, Any]:
    manifest = read_parser_failure_manifest(manifest_path, expected_sha256)
    derivation_registered_commit = _full_git_object(
        derivation_registered_commit,
        "derivation_registered_commit",
    )
    derivation_parser_blob_sha = _full_git_object(
        derivation_parser_blob_sha,
        "derivation_parser_blob_sha",
    )
    raw_path_value = manifest.get("raw_html_path")
    raw_sha = manifest.get("raw_html_sha256")
    raw_bytes = manifest.get("raw_content_bytes")
    if not isinstance(raw_path_value, str) or not isinstance(raw_sha, str):
        raise ValueError("EDEKA parser failure raw binding is missing")
    raw_path = Path(raw_path_value).expanduser().resolve()
    raw = raw_path.read_bytes()
    if len(raw) != raw_bytes or sha256(raw).hexdigest() != raw_sha:
        raise ValueError("EDEKA parser failure retained raw binding mismatch")

    collected_at_raw = manifest.get("collected_at")
    snapshot_id_raw = manifest.get("snapshot_id")
    if not isinstance(collected_at_raw, str) or not isinstance(snapshot_id_raw, str):
        raise ValueError("EDEKA parser failure replay identity is incomplete")
    collected_at = datetime.fromisoformat(collected_at_raw)
    from app.parsers.edeka import EdekaParserContext, parse_edeka_html

    context = EdekaParserContext(
        snapshot_id=UUID(snapshot_id_raw),
        source_url=_EXPECTED_SOURCE_URL,
        collected_at=collected_at,
        public_market_id=_EXPECTED_PUBLIC_MARKET_ID,
        internal_market_id=_EXPECTED_INTERNAL_MARKET_ID,
        store_name=_EXPECTED_STORE_NAME,
    )
    derivation_implementation, derivation_version = _runtime_python_identity()
    result: dict[str, Any] = {
        "schema_version": 1,
        "result": "fail",
        "source_registered_commit": manifest["source_registered_commit"],
        "source_parser_blob_sha": manifest["source_parser_blob_sha"],
        "source_python_implementation": manifest["python_implementation"],
        "source_python_version": manifest["python_version"],
        "derivation_registered_commit": derivation_registered_commit,
        "derivation_parser_blob_sha": derivation_parser_blob_sha,
        "derivation_python_implementation": derivation_implementation,
        "derivation_python_version": derivation_version,
        "parser_contract_version": PARSER_CONTRACT_VERSION,
        "raw_html_sha256": raw_sha,
        "network_refetch": False,
        "production_database_write": False,
    }
    try:
        offers = parse_edeka_html(raw, context)
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["error"] = f"{type(exc).__name__}: {exc}"[:2000]
        return result
    result["result"] = "pass"
    result["offer_count"] = len(offers)
    return result


def cleanup_failure_evidence(
    raw_snapshot_dir: Path,
    *,
    max_manifests: int = PARSER_FAILURE_RETENTION_MAX_MANIFESTS,
    apply: bool = False,
) -> dict[str, Any]:
    if max_manifests < 1:
        raise ValueError("EDEKA failure evidence retention must keep at least one manifest")
    root = raw_snapshot_dir.expanduser().resolve() / "edeka"
    if not root.exists():
        return {"kept": 0, "expired": [], "raw_candidates": [], "applied": apply}
    manifests = sorted(root.glob(_FAILURE_GLOB), key=lambda path: path.name, reverse=True)
    keep = manifests[:max_manifests]
    expire = manifests[max_manifests:]

    referenced_raw: set[Path] = set()
    for path in root.glob("*.json"):
        if path in expire:
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        raw_value = value.get("raw_html_path") if isinstance(value, dict) else None
        if isinstance(raw_value, str):
            referenced_raw.add(Path(raw_value).expanduser().resolve())

    raw_candidates: set[Path] = set()
    for path in expire:
        value = json.loads(path.read_text(encoding="utf-8"))
        raw_value = value.get("raw_html_path") if isinstance(value, dict) else None
        if isinstance(raw_value, str):
            raw_path = Path(raw_value).expanduser().resolve()
            if raw_path.parent == root and raw_path not in referenced_raw:
                raw_candidates.add(raw_path)

    if apply:
        for path in expire:
            path.unlink()
        for path in sorted(raw_candidates):
            if path.exists() and path.is_file() and not path.is_symlink():
                path.unlink()

    return {
        "kept": len(keep),
        "expired": [str(path) for path in expire],
        "raw_candidates": [str(path) for path in sorted(raw_candidates)],
        "applied": apply,
    }
