from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any


SCHEMA = "hermes.web-w0-source-baseline.v1"
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SOURCE_PATHS = (
    "backend/app/ui/index.html",
    "backend/app/ui/styles.css",
    "backend/app/ui/app.js",
    "backend/app/ui/accessibility-fixes.css",
    "backend/app/ui/accessibility-fixes.js",
    "backend/app/ui/weekly-payload-bridge.js",
    "backend/app/ui/ui-architecture-contract.json",
    "backend/app/ui_bundle.py",
)

EXTERNAL_EVIDENCE = {
    "production_ui_html": {
        "state": "not_observed",
        "required_observation": "real read-only production /ui fetch",
        "required_fields": ["byte_count", "sha256"],
    },
    "response_headers": {
        "state": "not_observed",
        "required_observation": "real read-only public/origin HTTP observations",
        "targets": [
            "/ui",
            "referenced_ui_javascript",
            "referenced_ui_stylesheet",
            "/api/v1/deals/weekly",
            "/api/v1/deals/current",
        ],
        "required_fields": [
            "cache-control",
            "content-security-policy",
            "content-type",
            "etag",
            "last-modified",
            "vary",
        ],
    },
    "browser_load": {
        "state": "not_observed",
        "required_observation": "real reproducible browser measurement",
        "scenarios": [
            "desktop_cold",
            "desktop_warm",
            "mobile_cold",
            "mobile_warm",
        ],
        "required_fields": [
            "lighthouse_or_equivalent",
            "web_vitals",
            "transferred_bytes",
        ],
    },
    "startup_waterfall": {
        "state": "not_observed",
        "required_observation": "real browser network waterfall",
        "required_fields": [
            "request_count",
            "transferred_bytes",
            "critical_sequence",
            "duplicate_work",
        ],
    },
    "chrome_coverage": {
        "state": "not_observed",
        "required_observation": "real Chrome Coverage session",
        "required_fields": [
            "first_render_css",
            "first_render_javascript",
            "normal_interaction_css",
            "normal_interaction_javascript",
        ],
    },
    "keyboard_only": {
        "state": "not_observed",
        "required_observation": "real keyboard-only browser walkthrough",
        "required_fields": [
            "shopping_list_drawer",
            "product_detail",
            "deal_detail",
            "search",
            "weekly_navigation",
            "bottom_navigation",
        ],
    },
}


class BaselineError(RuntimeError):
    """Raised when a deterministic W0 source baseline cannot be produced safely."""


def _validate_git_sha(value: str) -> str:
    if not GIT_SHA_RE.fullmatch(value):
        raise BaselineError("git SHA must be exactly 40 lowercase hexadecimal characters")
    return value


def _safe_regular_file(repo_root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise BaselineError(f"unsafe repository-relative path: {relative_path}")

    if repo_root.is_symlink():
        raise BaselineError(f"repository root must not be a symlink: {repo_root}")
    try:
        resolved_root = repo_root.resolve(strict=True)
    except OSError as exc:
        raise BaselineError(f"repository root is unavailable: {repo_root}") from exc
    if not resolved_root.is_dir():
        raise BaselineError(f"repository root is not a directory: {repo_root}")

    current = resolved_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise BaselineError(f"source path contains a symlink: {relative_path}")

    try:
        resolved = current.resolve(strict=True)
    except OSError as exc:
        raise BaselineError(f"required source file is missing: {relative_path}") from exc
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise BaselineError(f"source path escapes repository root: {relative_path}") from exc
    if not resolved.is_file():
        raise BaselineError(f"required source path is not a regular file: {relative_path}")
    return resolved


def _inventory_entry(repo_root: Path, relative_path: str) -> dict[str, Any]:
    path = _safe_regular_file(repo_root, relative_path)
    payload = path.read_bytes()
    return {
        "path": relative_path,
        "byte_count": len(payload),
        "sha256": sha256(payload).hexdigest(),
    }


def _inventory_fingerprint(entries: list[dict[str, Any]]) -> str:
    digest = sha256()
    for entry in entries:
        digest.update(
            (
                f"{entry['path']}\0{entry['byte_count']}\0{entry['sha256']}\n"
            ).encode("utf-8")
        )
    return digest.hexdigest()


def build_baseline(repo_root: Path, git_sha: str) -> dict[str, Any]:
    git_sha = _validate_git_sha(git_sha)
    inventory = [_inventory_entry(repo_root, path) for path in SOURCE_PATHS]
    return {
        "schema": SCHEMA,
        "git_sha": git_sha,
        "source_only": True,
        "source_inventory": inventory,
        "source_totals": {
            "file_count": len(inventory),
            "byte_count": sum(entry["byte_count"] for entry in inventory),
            "inventory_fingerprint_sha256": _inventory_fingerprint(inventory),
        },
        "external_evidence": json.loads(json.dumps(EXTERNAL_EVIDENCE)),
        "safety": {
            "raw_offer_or_api_payloads_included": False,
            "cookies_or_credentials_included": False,
            "production_browser_observation_claimed": False,
            "production_header_observation_claimed": False,
            "w0_exit_gate_satisfied_by_this_manifest": False,
        },
    }


def render_baseline(baseline: dict[str, Any]) -> str:
    return json.dumps(baseline, indent=2, sort_keys=True) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Emit a deterministic sanitized Hermes Deals W0 source baseline",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        required=True,
        help="Hermes Deals repository root",
    )
    parser.add_argument(
        "--git-sha",
        required=True,
        help="Exact 40-character lowercase Git commit SHA to bind into the manifest",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output JSON path; stdout is used when omitted",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        rendered = render_baseline(build_baseline(args.repo_root, args.git_sha))
        if args.output is None:
            print(rendered, end="")
        else:
            if args.output.is_symlink():
                raise BaselineError(f"output path must not be a symlink: {args.output}")
            parent = args.output.parent
            if not parent.exists() or not parent.is_dir() or parent.is_symlink():
                raise BaselineError(f"output parent must be an existing real directory: {parent}")
            args.output.write_text(rendered, encoding="utf-8", newline="\n")
    except (BaselineError, OSError) as exc:
        raise SystemExit(f"W0_SOURCE_BASELINE=FAIL: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
