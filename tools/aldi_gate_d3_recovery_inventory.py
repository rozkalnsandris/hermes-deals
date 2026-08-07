#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile

MODE = "ALDI_GATE_D3_RECOVERY_INVENTORY_V01"
ISSUE_NUMBER = 266
A21_ARCHIVE_SHA256 = "fa16df4db701e90f38bea0387a278750415ba03628f1fe1cc34ffb2833f2985d"
PAGE_RE = re.compile(r"^page-(\d{3})\.img$")
DECISIONS = {
    "RECOVERY_CANDIDATE_FOUND",
    "NO_RECOVERY_CANDIDATE",
    "AMBIGUOUS_RECOVERY_CANDIDATES",
}


class InventoryError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InventoryError(message)


def sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_format(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "webp"
    return None


def safe_relative(path: Path, root: Path) -> str:
    resolved = path.resolve(strict=False)
    root_resolved = root.resolve(strict=True)
    require(resolved == root_resolved or root_resolved in resolved.parents, "path escaped state root")
    return "." if resolved == root_resolved else resolved.relative_to(root_resolved).as_posix()


def safe_walk(root: Path):
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirs[:] = sorted(
            name for name in dirs
            if not (current_path / name).is_symlink()
        )
        yield current_path, sorted(files)


def manifest_summary(path: Path, root: Path) -> dict:
    row = {
        "path": safe_relative(path, root),
        "regular_file": False,
        "json_valid": False,
        "current_rows": 0,
        "preview_rows": 0,
        "other_rows": 0,
    }
    if not path.is_file() or path.is_symlink():
        return row
    row["regular_file"] = True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("rows") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return row
        row["json_valid"] = True
        counts = Counter(
            item.get("label") if isinstance(item, dict) else None
            for item in rows
        )
        row["current_rows"] = counts.get("current", 0)
        row["preview_rows"] = counts.get("preview", 0)
        row["other_rows"] = len(rows) - row["current_rows"] - row["preview_rows"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    return row


def collect_directory_family(page_images: Path, root: Path) -> dict:
    candidate = {
        "kind": "directory",
        "root": safe_relative(page_images.parent.parent, root),
        "page_images_root": safe_relative(page_images, root),
        "current_count": 0,
        "preview_count": 0,
        "complete_49_plus_41": False,
        "identity_sha256": None,
        "invalid_file_count": 0,
    }
    canonical = []
    complete = True
    for label, expected in (("current", 49), ("preview", 41)):
        directory = page_images / label
        if not directory.is_dir() or directory.is_symlink():
            complete = False
            continue
        matched = []
        for path in sorted(directory.iterdir(), key=lambda p: p.name):
            match = PAGE_RE.fullmatch(path.name)
            if not match:
                continue
            if not path.is_file() or path.is_symlink():
                candidate["invalid_file_count"] += 1
                complete = False
                continue
            page = int(match.group(1))
            data = path.read_bytes()
            fmt = image_format(data)
            if len(data) < 10_000 or fmt is None:
                candidate["invalid_file_count"] += 1
                complete = False
                continue
            matched.append(page)
            canonical.append({
                "label": label,
                "page_number": page,
                "bytes": len(data),
                "sha256": sha256(data).hexdigest(),
                "format": fmt,
            })
        candidate[f"{label}_count"] = len(matched)
        if matched != list(range(1, expected + 1)):
            complete = False
    if complete and candidate["current_count"] == 49 and candidate["preview_count"] == 41:
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        candidate["complete_49_plus_41"] = True
        candidate["identity_sha256"] = sha256(encoded).hexdigest()
    return candidate


def safe_tar_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def archive_inventory(path: Path, root: Path) -> dict:
    result = {
        "path": safe_relative(path, root),
        "sha256": None,
        "is_a21_archive": False,
        "safe": False,
        "unsafe_reason": None,
        "manifest_member_count": 0,
        "complete_49_plus_41_count": 0,
        "complete_identities": [],
    }
    if not path.is_file() or path.is_symlink():
        result["unsafe_reason"] = "not_regular_file"
        return result
    digest = sha_file(path)
    result["sha256"] = digest
    if digest == A21_ARCHIVE_SHA256:
        result["is_a21_archive"] = True
        result["safe"] = True
        return result
    try:
        with tarfile.open(path, "r:*") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if len(names) != len(set(names)):
                result["unsafe_reason"] = "duplicate_member_name"
                return result
            for member in members:
                if not safe_tar_name(member.name):
                    result["unsafe_reason"] = "unsafe_member_path"
                    return result
                if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                    result["unsafe_reason"] = "unsafe_member_type"
                    return result
                if not (member.isfile() or member.isdir()):
                    result["unsafe_reason"] = "unsupported_member_type"
                    return result
            result["manifest_member_count"] = sum(
                1 for member in members
                if member.isfile() and PurePosixPath(member.name).name == "page-image-manifest.json"
            )
            groups: dict[str, dict[str, dict[int, tarfile.TarInfo]]] = defaultdict(
                lambda: {"current": {}, "preview": {}}
            )
            marker = "/raw/page-images/"
            for member in members:
                if not member.isfile():
                    continue
                normalized = "/" + member.name.lstrip("/")
                if marker not in normalized:
                    continue
                prefix, suffix = normalized.split(marker, 1)
                parts = PurePosixPath(suffix).parts
                if len(parts) != 2 or parts[0] not in {"current", "preview"}:
                    continue
                match = PAGE_RE.fullmatch(parts[1])
                if not match:
                    continue
                groups[prefix][parts[0]][int(match.group(1))] = member
            identities = []
            for prefix in sorted(groups):
                group = groups[prefix]
                if sorted(group["current"]) != list(range(1, 50)):
                    continue
                if sorted(group["preview"]) != list(range(1, 42)):
                    continue
                canonical = []
                valid = True
                for label, expected in (("current", 49), ("preview", 41)):
                    for page_number in range(1, expected + 1):
                        member = group[label][page_number]
                        extracted = archive.extractfile(member)
                        if extracted is None:
                            valid = False
                            break
                        data = extracted.read()
                        fmt = image_format(data)
                        if len(data) < 10_000 or fmt is None:
                            valid = False
                            break
                        canonical.append({
                            "label": label,
                            "page_number": page_number,
                            "bytes": len(data),
                            "sha256": sha256(data).hexdigest(),
                            "format": fmt,
                        })
                    if not valid:
                        break
                if valid:
                    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
                    identities.append(sha256(encoded).hexdigest())
            result["complete_identities"] = sorted(set(identities))
            result["complete_49_plus_41_count"] = len(result["complete_identities"])
            result["safe"] = True
    except (OSError, tarfile.TarError):
        result["unsafe_reason"] = "tar_open_failed"
    return result


def build_inventory(root: Path) -> dict:
    require(root.is_dir() and not root.is_symlink(), "state root missing or unsafe")
    manifests = []
    page_image_roots = set()
    archives = []
    for current, files in safe_walk(root):
        for name in files:
            path = current / name
            if name == "page-image-manifest.json":
                manifests.append(manifest_summary(path, root))
            if name.endswith(".tar.gz") or name.endswith(".tgz"):
                archives.append(archive_inventory(path, root))
        if current.name == "page-images" and (current / "current").exists() and (current / "preview").exists():
            page_image_roots.add(current)
    directory_candidates = [
        collect_directory_family(path, root)
        for path in sorted(page_image_roots, key=lambda p: safe_relative(p, root))
        if path.is_dir() and not path.is_symlink()
    ]
    complete = []
    for item in directory_candidates:
        if item["complete_49_plus_41"]:
            complete.append({"kind": "directory", "source": item["page_images_root"], "identity_sha256": item["identity_sha256"]})
    for item in archives:
        if item["is_a21_archive"] or not item["safe"]:
            continue
        for identity in item["complete_identities"]:
            complete.append({"kind": "archive", "source": item["path"], "identity_sha256": identity})
    identities = sorted({item["identity_sha256"] for item in complete})
    if not identities:
        decision = "NO_RECOVERY_CANDIDATE"
    elif len(identities) == 1:
        decision = "RECOVERY_CANDIDATE_FOUND"
    else:
        decision = "AMBIGUOUS_RECOVERY_CANDIDATES"
    require(decision in DECISIONS, "invalid decision")
    payload = {
        "schema_version": 1,
        "mode": MODE,
        "issue_number": ISSUE_NUMBER,
        "decision": decision,
        "state_root": ".",
        "manifest_count": len(manifests),
        "directory_candidate_count": len(directory_candidates),
        "archive_count": len(archives),
        "complete_recovery_source_count": len(complete),
        "distinct_complete_identity_count": len(identities),
        "manifests": manifests,
        "directory_candidates": directory_candidates,
        "archives": archives,
        "complete_recovery_sources": complete,
        "complete_identities": identities,
        "next_step": "bind_recovered_immutable_family" if decision == "RECOVERY_CANDIDATE_FOUND" else (
            "resolve_recovery_candidate_ambiguity" if decision == "AMBIGUOUS_RECOVERY_CANDIDATES" else "manual_evidence_recovery_required"
        ),
        "raw_evidence_exported": False,
        "raw_exception_exported": False,
        "production_eligible": False,
        "review_pack_execution_authorized": False,
        "safety": {
            "inventory_only": True,
            "network_acquisition_authorized": False,
            "archive_extraction_authorized": False,
            "source_or_corpus_mutation_authorized": False,
            "manifest_regeneration_authorized": False,
            "parser_execution_authorized": False,
            "candidate_creation_authorized": False,
            "review_write_authorized": False,
            "automatic_approval_authorized": False,
            "automatic_publication_authorized": False,
            "production_database_write_authorized": False,
            "production_deployment_authorized": False,
            "scheduler_or_retry_authorized": False,
            "production_canary_authorized": False,
            "b15m2_v08_action_authorized": False,
            "strict_49_plus_41_frozen_contract_unchanged": True,
        },
    }
    fingerprint_source = dict(payload)
    fingerprint_source.pop("diagnostic_fingerprint", None)
    payload["diagnostic_fingerprint"] = sha256(
        json.dumps(fingerprint_source, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.state_root)
    output = Path(args.output)
    require(not output.exists(), "output already exists")
    payload = build_inventory(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(payload["decision"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
