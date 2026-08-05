from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys
from typing import Any


TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from lidl_parser_provenance.verify_parser_runtime_graph import (  # noqa: E402
    ParserRuntimeGraphError,
    load_graph,
    verify_graph,
)


SCAN_ROOTS = (
    Path("backend/app"),
    Path("tools"),
    Path("backend/tests"),
)
TARGET_MODULES = {
    "lidl_parser_provenance.lidl_v631_runtime": "v631-runtime-loader",
    "app.lidl_weekly_semantics": "weekly-semantics",
    "app.lidl_weekly_completeness_contract": "weekly-completeness-contract",
    "app.lidl_family_source_discovery": "family-source-discovery",
    "app.lidl_review_seed_reconciliation": "review-seed-reconciliation",
}
REQUIRED_CANONICAL_ROUTES = {
    "weekly-one-shot": "v631-runtime-loader",
    "weekly-staging": "v631-runtime-loader",
    "weekly-completeness": "v631-runtime-loader",
}


class LidlIssue22ClosureError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LidlIssue22ClosureError(message)


def _is_test_path(relative: str) -> bool:
    path = Path(relative)
    return "tests" in path.parts or path.name.startswith("test_")


def _iter_python_files(repo_root: Path) -> list[Path]:
    result: list[Path] = []
    for relative_root in SCAN_ROOTS:
        root = repo_root / relative_root
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            result.append(path)
    return sorted(result)


def _imported_modules(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise LidlIssue22ClosureError(f"cannot parse Python source {path}: {exc}") from exc

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def collect_direct_importers(repo_root: Path) -> dict[str, list[str]]:
    root = repo_root.resolve()
    importers: dict[str, set[str]] = {module: set() for module in TARGET_MODULES}
    for path in _iter_python_files(root):
        relative = path.relative_to(root).as_posix()
        modules = _imported_modules(path)
        for target_module in TARGET_MODULES:
            if target_module in modules:
                importers[target_module].add(relative)
    return {
        module: sorted(paths)
        for module, paths in sorted(importers.items())
    }


def collect_lidl_python_inventory(repo_root: Path) -> dict[str, list[str]]:
    root = repo_root.resolve()
    inventory = {
        "backend_modules": [],
        "tool_entrypoints": [],
        "tests": [],
    }
    for path in _iter_python_files(root):
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        if "lidl" not in relative.casefold() and "lidl" not in text.casefold():
            continue
        if _is_test_path(relative):
            inventory["tests"].append(relative)
        elif relative.startswith("backend/app/"):
            inventory["backend_modules"].append(relative)
        else:
            inventory["tool_entrypoints"].append(relative)
    return {
        category: sorted(paths)
        for category, paths in inventory.items()
    }


def _node_map(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_nodes = graph.get("nodes")
    _require(isinstance(raw_nodes, list) and raw_nodes, "graph nodes must be non-empty")
    result: dict[str, dict[str, Any]] = {}
    for raw in raw_nodes:
        _require(isinstance(raw, dict), "graph node must be an object")
        node_id = str(raw.get("id") or "")
        path = str(raw.get("path") or "")
        _require(node_id and path, "graph node must declare id and path")
        result[node_id] = raw
    return result


def _edge_pairs(graph: dict[str, Any]) -> set[tuple[str, str]]:
    raw_edges = graph.get("edges")
    _require(isinstance(raw_edges, list), "graph edges must be a list")
    result: set[tuple[str, str]] = set()
    for raw in raw_edges:
        _require(isinstance(raw, dict), "graph edge must be an object")
        if raw.get("kind") == "imports":
            result.add((str(raw.get("from") or ""), str(raw.get("to") or "")))
    return result


def validate_direct_import_contract(
    graph: dict[str, Any],
    direct_importers: dict[str, list[str]],
) -> dict[str, Any]:
    nodes = _node_map(graph)
    path_to_node = {
        str(node["path"]): node_id
        for node_id, node in nodes.items()
    }
    import_edges = _edge_pairs(graph)

    required_pairs = {
        *REQUIRED_CANONICAL_ROUTES.items(),
        ("v631-runtime-loader", "weekly-semantics"),
        ("weekly-semantic-view", "weekly-semantics"),
        ("weekly-semantic-view", "weekly-completeness-contract"),
    }
    missing_required = sorted(required_pairs - import_edges)
    _require(
        not missing_required,
        "required Lidl runtime routes are absent from graph: "
        + ", ".join(f"{source}->{target}" for source, target in missing_required),
    )

    canonical_module = "lidl_parser_provenance.lidl_v631_runtime"
    source_importers: dict[str, list[str]] = {}
    support_importers: dict[str, list[str]] = {}
    test_importers: dict[str, list[str]] = {}
    for module_name, target_node in sorted(TARGET_MODULES.items()):
        paths = direct_importers.get(module_name)
        _require(isinstance(paths, list), f"missing importer inventory for {module_name}")
        source_paths: list[str] = []
        support_paths: list[str] = []
        test_paths: list[str] = []
        for relative in paths:
            if _is_test_path(relative):
                _require(
                    relative.startswith("backend/tests/"),
                    f"test importer is outside backend/tests: {relative}",
                )
                test_paths.append(relative)
                continue
            source_node = path_to_node.get(relative)
            if source_node is None:
                _require(
                    module_name != canonical_module,
                    f"non-test Lidl runtime importer is absent from graph: {relative}",
                )
                support_paths.append(relative)
                continue
            _require(
                (source_node, target_node) in import_edges,
                f"graph lacks import edge {source_node}->{target_node} for {relative}",
            )
            source_paths.append(relative)
        source_importers[module_name] = sorted(source_paths)
        support_importers[module_name] = sorted(support_paths)
        test_importers[module_name] = sorted(test_paths)

    return {
        "source_importers": source_importers,
        "support_importers": support_importers,
        "test_importers": test_importers,
        "required_route_count": len(required_pairs),
    }


def verify_issue_22_closure(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    base_result = verify_graph(root)
    graph = load_graph(root)
    direct_importers = collect_direct_importers(root)
    import_contract = validate_direct_import_contract(graph, direct_importers)
    inventory = collect_lidl_python_inventory(root)

    historical = graph.get("historical_identities")
    _require(isinstance(historical, list) and historical, "historical identities are required")
    dead_r6 = next(
        (
            identity
            for identity in historical
            if identity.get("name") == "dead noncanonical r6_parser.py"
        ),
        None,
    )
    _require(isinstance(dead_r6, dict), "r6_parser.py quarantine identity is missing")
    _require(
        dead_r6.get("status") == "quarantined_by_absence",
        "r6_parser.py must remain quarantined by absence",
    )
    _require(
        dead_r6.get("allowed_importers") == [],
        "r6_parser.py quarantine must allow no importers",
    )
    _require(
        str(dead_r6.get("recovery_evidence") or "") != "",
        "r6_parser.py quarantine lacks recovery evidence",
    )

    return {
        "result": "PASS",
        "issue": 22,
        "base_graph_result": base_result["result"],
        "canonical_runtime_node": base_result["canonical_runtime_node"],
        "canonical_parser_version": base_result["canonical_parser_version"],
        "node_count": base_result["node_count"],
        "edge_count": base_result["edge_count"],
        "corpus_binding_count": base_result["corpus_binding_count"],
        "lidl_python_inventory": inventory,
        "direct_importers": direct_importers,
        "import_contract": import_contract,
        "r6_parser_status": dead_r6["status"],
        "production_deploy_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "parser_behavior_changed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the complete read-only Lidl issue #22 closure contract"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    args = parser.parse_args()
    try:
        result = verify_issue_22_closure(args.repo_root)
    except (ParserRuntimeGraphError, LidlIssue22ClosureError) as exc:
        print(str(exc))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
