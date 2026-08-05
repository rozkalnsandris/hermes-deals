from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


GRAPH_RELATIVE_PATH = Path("tools/lidl_parser_provenance/parser_runtime_graph.json")
PARSER_MARKERS = (
    "PARSER_VERSION",
    "load_lidl_v631",
    "parse_lidl_pdf",
    "analyze_lidl_pdf",
)
SEARCH_ROOTS = (
    Path("backend/app"),
    Path("tools"),
)


class ParserRuntimeGraphError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_graph(repo_root: Path) -> dict[str, Any]:
    path = repo_root / GRAPH_RELATIVE_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParserRuntimeGraphError(f"cannot load parser runtime graph: {exc}") from exc
    if not isinstance(payload, dict):
        raise ParserRuntimeGraphError("parser runtime graph root must be an object")
    return payload


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ParserRuntimeGraphError(message)


def _node_map(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_nodes = graph.get("nodes")
    _require(isinstance(raw_nodes, list) and raw_nodes, "graph nodes must be non-empty")
    result: dict[str, dict[str, Any]] = {}
    for raw in raw_nodes:
        _require(isinstance(raw, dict), "every graph node must be an object")
        node_id = str(raw.get("id") or "")
        _require(node_id != "", "graph node id is required")
        _require(node_id not in result, f"duplicate graph node id: {node_id}")
        result[node_id] = raw
    return result


def _declared_parser_candidates(repo_root: Path) -> set[str]:
    candidates: set[str] = set()
    for search_root in SEARCH_ROOTS:
        root = repo_root / search_root
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if path.name.startswith("test_") or "tests" in path.parts:
                continue
            relative = path.relative_to(repo_root).as_posix()
            if "lidl" not in relative.casefold():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if any(marker in text for marker in PARSER_MARKERS):
                candidates.add(relative)
    return candidates


def verify_graph(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    graph = load_graph(root)
    _require(graph.get("schema_version") == 1, "unsupported graph schema_version")
    _require(graph.get("issue") == 22, "graph must remain bound to issue 22")

    nodes = _node_map(graph)
    canonical_id = str(graph.get("canonical_runtime_node") or "")
    _require(canonical_id in nodes, "canonical runtime node is missing")
    canonical = nodes[canonical_id]
    _require(
        canonical.get("role") == "canonical_active_runtime_adapter",
        "canonical node has the wrong role",
    )
    _require(canonical.get("lifecycle") == "active", "canonical node is not active")
    _require(canonical.get("runtime_imported") is True, "canonical node is not runtime imported")

    roles = [str(node.get("role") or "") for node in nodes.values()]
    _require(all(roles), "every node must declare a role")
    _require(
        roles.count("canonical_active_runtime_adapter") == 1,
        "exactly one canonical active runtime adapter is required",
    )

    bootstrap_hashes: dict[str, str] = {}
    verified_hashes: dict[str, str] = {}
    declared_paths: set[str] = set()
    for node_id, node in nodes.items():
        relative = str(node.get("path") or "")
        _require(relative != "", f"node {node_id} has no path")
        _require(relative not in declared_paths, f"duplicate graph path: {relative}")
        declared_paths.add(relative)
        path = root / relative
        _require(path.is_file(), f"declared graph path is missing: {relative}")
        actual = sha256_file(path)
        expected = str(node.get("sha256") or "")
        _require(expected != "", f"node {node_id} has no sha256")
        if expected == "AUTO":
            bootstrap_hashes[relative] = actual
        else:
            _require(
                expected == actual,
                f"SHA256 drift for {relative}: expected {expected}, got {actual}",
            )
        verified_hashes[relative] = actual

    edges = graph.get("edges")
    _require(isinstance(edges, list), "graph edges must be a list")
    for raw_edge in edges:
        _require(isinstance(raw_edge, dict), "every graph edge must be an object")
        source_id = str(raw_edge.get("from") or "")
        target_id = str(raw_edge.get("to") or "")
        _require(source_id in nodes, f"edge source is undeclared: {source_id}")
        _require(target_id in nodes, f"edge target is undeclared: {target_id}")
        token = str(raw_edge.get("evidence_token") or "")
        _require(token != "", f"edge {source_id}->{target_id} lacks evidence token")
        source_path = root / str(nodes[source_id]["path"])
        source_text = source_path.read_text(encoding="utf-8")
        _require(
            token in source_text,
            f"edge evidence is missing in {nodes[source_id]['path']}: {token}",
        )

    manifest_relative = str(graph.get("corpus_manifest") or "")
    _require(manifest_relative != "", "corpus manifest path is required")
    manifest_path = root / manifest_relative
    _require(manifest_path.is_file(), "corpus manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_identity = manifest.get("source_identity") or {}
    _require(
        source_identity.get("parser_version") == graph.get("canonical_parser_version"),
        "canonical parser version does not match corpus manifest",
    )
    _require(
        source_identity.get("r61_base_sha256")
        == nodes["v631-frozen-base"].get("sha256"),
        "frozen base SHA does not match corpus manifest",
    )
    _require(
        source_identity.get("authoritative_v631_sha256")
        == nodes["v631-shadow-parser"].get("sha256"),
        "shadow parser SHA does not match corpus manifest",
    )
    bindings = manifest.get("corpus_bindings")
    _require(isinstance(bindings, list) and len(bindings) >= 2, "at least two immutable corpus bindings are required")
    for binding in bindings:
        _require(isinstance(binding, dict), "corpus binding must be an object")
        for key in ("flyer_key", "scan", "pdf_sha256", "raw_sha256"):
            value = str(binding.get(key) or "")
            _require(value != "", f"corpus binding lacks {key}")
        for key in ("pdf_sha256", "raw_sha256"):
            value = str(binding[key])
            _require(len(value) == 64, f"corpus binding {key} is not a full SHA256")

    retention = graph.get("retention_policy") or {}
    _require(
        retention.get("mode") == "permanent_content_addressed_evidence",
        "frozen evidence retention must be permanent and content addressed",
    )
    _require(
        retention.get("removal_requires_recovery_proof") is True,
        "frozen evidence removal must require recovery proof",
    )
    for relative in retention.get("required_paths") or []:
        _require((root / str(relative)).is_file(), f"retained evidence is missing: {relative}")

    historical = graph.get("historical_identities")
    _require(isinstance(historical, list) and historical, "historical identities are required")
    for identity in historical:
        _require(isinstance(identity, dict), "historical identity must be an object")
        _require(identity.get("allowed_importers") == [], "historical identity importers must remain empty")
        for relative in identity.get("paths") or []:
            _require(
                not (root / str(relative)).exists(),
                f"historical parser path was reintroduced without a declared role: {relative}",
            )

    undeclared = sorted(_declared_parser_candidates(root) - declared_paths)
    _require(
        not undeclared,
        "Lidl parser-capable files are missing from the runtime graph: " + ", ".join(undeclared),
    )

    if bootstrap_hashes:
        raise ParserRuntimeGraphError(
            "BOOTSTRAP_SHA256=" + json.dumps(bootstrap_hashes, sort_keys=True)
        )

    return {
        "result": "PASS",
        "canonical_runtime_node": canonical_id,
        "canonical_parser_version": graph["canonical_parser_version"],
        "node_count": len(nodes),
        "edge_count": len(edges),
        "corpus_binding_count": len(bindings),
        "verified_sha256": verified_hashes,
        "production_deploy_authorized": False,
        "database_write_authorized": False,
        "parser_behavior_changed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the committed Lidl parser runtime graph")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    args = parser.parse_args()
    try:
        result = verify_graph(args.repo_root)
    except ParserRuntimeGraphError as exc:
        print(str(exc))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
