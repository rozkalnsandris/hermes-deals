#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import html
import importlib.util
import json
import re
from pathlib import Path
import shutil
import sys
from typing import Any, Callable, Iterable, Mapping

MODE = "ALDI_WEEKLY_GATE_D_VISUAL_REVIEW_PACK_V01"
DECISION = "READY_FOR_MANUAL_VISUAL_ADJUDICATION"
EXPECTED_A21_PROJECTION_SHA256 = (
    "64699b7ede52dcaa5b85f3306426f3b90399dd037209621a38bacd166161d5ea"
)
EXPECTED_PUBLICATION_COUNTS = {
    "auto_candidate": 346,
    "review_required": 54,
    "blocked_out_of_scope": 119,
}
EXPECTED_PAGE_COUNTS = {"current": 49, "preview": 41}
EXPECTED_GATE_B_PLAN_SHA256 = (
    "3188821faa36a6d9fb598fde521a59993e6cb11678a8160e4afead4ba4fcfdd4"
)
EXPECTED_PAGE3_SHA256 = (
    "ad297cdd2f3dc728f0114fcb8a06c6d2c6131f4b342173b134d9e99bd092ae7c"
)
TARGET_STATUSES = {"auto_candidate", "review_required"}
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class GateDError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateDError(message)


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def canonical_sha(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_image_format(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\xff\xd8"):
        return "jpeg", ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", ".png"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "webp", ".webp"
    raise GateDError("unknown image format")


def load_json(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file(), f"{label} is missing: {path}")
    require(not path.is_symlink(), f"symlinked {label} forbidden: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateDError(f"invalid {label}: {exc}") from exc
    require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    require(isinstance(value, Mapping), f"{label} must be an object")
    return value


def _strict_int(value: Any, label: str, *, minimum: int = 0) -> int:
    require(
        not isinstance(value, bool) and isinstance(value, int),
        f"{label} must be an integer",
    )
    require(value >= minimum, f"{label} must be >= {minimum}")
    return value


def load_projection(
    path: Path,
    *,
    expected_sha256: str = EXPECTED_A21_PROJECTION_SHA256,
    expected_counts: Mapping[str, int] = EXPECTED_PUBLICATION_COUNTS,
    expected_rows: int = 519,
) -> list[dict[str, Any]]:
    require(path.is_file(), f"A2.1 projection is missing: {path}")
    require(not path.is_symlink(), "symlinked A2.1 projection forbidden")
    require(sha_file(path) == expected_sha256, "A2.1 projection SHA256 mismatch")
    rows: list[dict[str, Any]] = []
    keys: set[tuple[str, str]] = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GateDError(f"invalid projection JSONL line {line_number}") from exc
        require(isinstance(raw, dict), f"projection row {line_number} must be an object")
        source_page = str(raw.get("source_page") or "")
        source_offer_id = str(raw.get("source_offer_id") or "")
        require(
            source_page in EXPECTED_PAGE_COUNTS,
            f"invalid source_page at line {line_number}",
        )
        require(bool(source_offer_id), f"missing source_offer_id at line {line_number}")
        key = (source_page, source_offer_id)
        require(key not in keys, f"duplicate projection offer identity: {key}")
        keys.add(key)
        publication = _mapping(raw.get("publication"), f"publication line {line_number}")
        status = str(publication.get("status") or "")
        require(status in expected_counts, f"invalid publication status at line {line_number}")
        rows.append(raw)
    require(len(rows) == expected_rows, "A2.1 projection row count drift")
    counts = Counter(str(row["publication"]["status"]) for row in rows)
    require(dict(counts) == dict(expected_counts), "A2.1 publication count drift")
    return rows


def validate_legacy_page_manifest(
    path: Path,
    *,
    expected_page_counts: Mapping[str, int] = EXPECTED_PAGE_COUNTS,
    minimum_image_bytes: int = 10_000,
) -> dict[str, Any]:
    payload = load_json(path, "legacy A3.0 page manifest")
    rows = payload.get("rows")
    require(isinstance(rows, list), "legacy page manifest rows are missing")
    expected = {
        (label, page)
        for label, count in expected_page_counts.items()
        for page in range(1, count + 1)
    }
    observed: set[tuple[str, int]] = set()
    compact: list[dict[str, Any]] = []
    for raw in rows:
        row = _mapping(raw, "legacy page manifest row")
        label = str(row.get("label") or "")
        page = _strict_int(row.get("page_number"), "legacy page number", minimum=1)
        pair = (label, page)
        require(pair in expected, f"unexpected legacy page identity: {pair}")
        require(pair not in observed, f"duplicate legacy page identity: {pair}")
        observed.add(pair)
        digest = str(row.get("sha256") or "")
        size = _strict_int(
            row.get("bytes"),
            "legacy page bytes",
            minimum=minimum_image_bytes,
        )
        image_format = str(row.get("format") or "")
        require(len(digest) == 64, f"invalid legacy page SHA: {pair}")
        require(
            image_format in {"jpeg", "png", "webp"},
            f"invalid legacy page format: {pair}",
        )
        compact.append(
            {
                "label": label,
                "page_number": page,
                "sha256": digest,
                "bytes": size,
                "format": image_format,
            }
        )
    require(observed == expected, "legacy page manifest is incomplete")
    compact.sort(key=lambda row: (row["label"], row["page_number"]))
    return {
        "rows": compact,
        "manifest_sha256": sha_file(path),
        "page_set_sha256": canonical_sha(
            [
                {
                    "label": row["label"],
                    "page_number": row["page_number"],
                    "sha256": row["sha256"],
                    "bytes": row["bytes"],
                }
                for row in compact
            ]
        ),
        "total_pages": len(compact),
    }


def validate_image(
    path: Path,
    *,
    expected_sha256: str,
    expected_bytes: int,
    expected_format: str,
) -> tuple[bytes, str]:
    require(path.is_file(), f"page image is missing: {path}")
    require(not path.is_symlink(), f"symlinked page image forbidden: {path}")
    data = path.read_bytes()
    require(len(data) == expected_bytes, f"page image byte count mismatch: {path}")
    require(
        sha256(data).hexdigest() == expected_sha256,
        f"page image SHA mismatch: {path}",
    )
    actual_format, suffix = detect_image_format(data)
    require(actual_format == expected_format, f"page image format mismatch: {path}")
    return data, suffix


def candidate_hint(row: Mapping[str, Any]) -> dict[str, Any]:
    identity = _mapping(row.get("identity"), "candidate identity")
    pricing = _mapping(row.get("pricing"), "candidate pricing")
    publication = _mapping(row.get("publication"), "candidate publication")
    source_page = str(row.get("source_page") or "")
    source_offer_id = str(row.get("source_offer_id") or "")
    display_title = str(identity.get("display_title_candidate") or "").strip()
    if not display_title:
        brand = str(identity.get("brand_raw") or "").strip()
        name = str(identity.get("name_raw") or "").strip()
        display_title = " ".join(value for value in (brand, name) if value)
    review_reasons = sorted(
        str(value)
        for value in (publication.get("review_reasons") or [])
        if str(value)
    )
    return {
        "offer_key": f"{source_page}:{source_offer_id}",
        "source_page": source_page,
        "source_offer_id": source_offer_id,
        "publication_status": str(publication.get("status") or ""),
        "display_title": display_title,
        "price_eur": (
            str(pricing.get("price_eur"))
            if pricing.get("price_eur") not in (None, "")
            else None
        ),
        "review_reasons": review_reasons,
    }


def build_legacy_ledger_template(
    projection_rows: Iterable[Mapping[str, Any]],
    page_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    hints = [
        candidate_hint(row)
        for row in projection_rows
        if str(_mapping(row.get("publication"), "publication").get("status") or "")
        in TARGET_STATUSES
    ]
    hints.sort(key=lambda row: row["offer_key"])
    pages = [
        {
            "source_page": row["label"],
            "page_number": row["page_number"],
            "page_sha256": row["sha256"],
            "card_id_prefix": f"{row['label']}:p{row['page_number']:03d}:c",
        }
        for row in page_manifest["rows"]
    ]
    return {
        "schema_version": 1,
        "source_page_set_sha256": page_manifest["page_set_sha256"],
        "cards": [],
        "pages": pages,
        "candidate_hints": hints,
        "instructions": [
            "Add one card row per visually distinct flyer offer card.",
            "Use normalized x/y/width/height values between 0 and 1.",
            "Assign explicit_offer_ids only when source identity is visually proven.",
            "Every in_scope/review card must match an offer or carry unmatched_reason.",
            "Do not add production approvals or publication decisions.",
        ],
    }


def load_gate_b_authoritative(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    tool = Path(__file__).with_name("aldi_weekly_gate_c_shadow_replay_preflight.py")
    require(tool.is_file(), f"Gate C preflight module is missing: {tool}")
    spec = importlib.util.spec_from_file_location("aldi_gate_c_for_gate_d", tool)
    require(spec is not None and spec.loader is not None, "cannot load Gate C preflight")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    plan, validated = module.load_gate_b_plan(path)
    return plan, validated


def safety_contract() -> dict[str, bool]:
    return {
        "review_pack_only": True,
        "network_acquisition_authorized": False,
        "parser_execution_authorized": False,
        "source_or_corpus_mutation_authorized": False,
        "candidate_creation_authorized": False,
        "production_database_write_authorized": False,
        "review_write_authorized": False,
        "automatic_approval_authorized": False,
        "automatic_publication_authorized": False,
        "production_deployment_authorized": False,
        "scheduler_or_retry_authorized": False,
        "production_canary_authorized": False,
        "b15m2_v08_action_authorized": False,
        "strict_41_of_41_gate_unchanged": True,
    }


def render_html(
    *,
    legacy_pages: list[dict[str, Any]],
    page3: dict[str, Any],
    hints: list[dict[str, Any]],
    identity: Mapping[str, Any],
) -> str:
    payload = {
        "legacy_pages": legacy_pages,
        "page3": page3,
        "candidate_hints": hints,
        "identity": identity,
    }
    embedded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    title = "ALDI Gate D visual adjudication pack"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root {{ color-scheme: light dark; font-family: system-ui,sans-serif; }}
body {{ margin:0; display:grid; grid-template-columns:280px 1fr; min-height:100vh; }}
aside {{ padding:16px; border-right:1px solid #8885; overflow:auto; }}
main {{ padding:18px; min-width:0; }}
button {{ width:100%; text-align:left; margin:2px 0; padding:7px; }}
img {{ max-width:100%; max-height:70vh; border:1px solid #8887; }}
.grid {{ display:grid; grid-template-columns:minmax(0,1.4fr) minmax(300px,.8fr); gap:18px; }}
.hints {{ max-height:70vh; overflow:auto; }}
.hint {{ border-bottom:1px solid #8885; padding:8px 0; }}
code {{ overflow-wrap:anywhere; }}
.badge {{ display:inline-block; padding:2px 7px; border:1px solid #8887; border-radius:999px; }}
@media (max-width:900px) {{
 body {{ display:block; }}
 aside {{ border-right:0; border-bottom:1px solid #8885; max-height:35vh; }}
 .grid {{ display:block; }}
}}
</style>
</head>
<body>
<aside>
<h1 style="font-size:1.1rem">{html.escape(title)}</h1>
<p><span class="badge">manual review only</span></p>
<input id="search" placeholder="Filter candidate hints" style="width:100%;box-sizing:border-box;padding:8px">
<div id="pages"></div>
</aside>
<main>
<h2 id="heading"></h2>
<p id="identity"></p>
<div class="grid">
<section><img id="image" alt="Selected flyer page"></section>
<section class="hints"><h3>Candidate hints</h3><div id="hints"></div></section>
</div>
</main>
<script id="data" type="application/json">{embedded}</script>
<script>
const DATA=JSON.parse(document.getElementById('data').textContent);
const pages=[...DATA.legacy_pages,DATA.page3];
let current=pages[0];
const pagesBox=document.getElementById('pages');
for(const page of pages){{
 const b=document.createElement('button');
 b.textContent=page.kind==='current_page3'?'NEW current page 3':`${{page.source_page}} page ${{page.page_number}}`;
 b.onclick=()=>select(page);
 pagesBox.appendChild(b);
}}
function select(page){{
 current=page;
 document.getElementById('heading').textContent=
  page.kind==='current_page3'?'Current page 3 — fresh Review-only extraction':
  `${{page.source_page}} page ${{page.page_number}}`;
 document.getElementById('image').src=page.image_path;
 document.getElementById('identity').innerHTML=`SHA256 <code>${{page.sha256}}</code>`;
 renderHints();
}}
function renderHints(){{
 const q=document.getElementById('search').value.toLowerCase();
 const source=current.kind==='current_page3'?'current':current.source_page;
 const rows=DATA.candidate_hints.filter(x=>x.source_page===source).filter(x=>
  !q || JSON.stringify(x).toLowerCase().includes(q));
 const box=document.getElementById('hints'); box.textContent='';
 for(const row of rows){{
  const div=document.createElement('div'); div.className='hint';
  const strong=document.createElement('strong');
  strong.textContent=row.display_title||'(no title)';
  const key=document.createElement('code');
  key.textContent=row.offer_key;
  const meta=document.createElement('span');
  meta.textContent=`status=${{row.publication_status}} price=${{row.price_eur??'—'}}`;
  div.append(strong,document.createElement('br'),key,document.createElement('br'),meta);
  box.appendChild(div);
 }}
}}
document.getElementById('search').addEventListener('input',renderHints);
select(current);
</script>
</body>
</html>
"""


@dataclass(frozen=True)
class PackInputs:
    projection: Path
    legacy_page_manifest: Path
    legacy_page_root: Path
    gate_b_plan: Path
    current_pages_root: Path
    output: Path
    commit_sha: str


def create_review_pack(
    inputs: PackInputs,
    *,
    gate_b_loader: Callable[
        [Path], tuple[dict[str, Any], dict[str, Any]]
    ] = load_gate_b_authoritative,
    expected_projection_sha256: str = EXPECTED_A21_PROJECTION_SHA256,
    expected_projection_counts: Mapping[str, int] = EXPECTED_PUBLICATION_COUNTS,
    expected_projection_rows: int = 519,
    expected_page_counts: Mapping[str, int] = EXPECTED_PAGE_COUNTS,
    minimum_image_bytes: int = 10_000,
) -> dict[str, Any]:
    require(
        COMMIT_SHA_RE.fullmatch(inputs.commit_sha) is not None,
        "commit SHA must be 40 lowercase hex characters",
    )
    require(not inputs.output.exists(), f"output already exists: {inputs.output}")
    projection_rows = load_projection(
        inputs.projection,
        expected_sha256=expected_projection_sha256,
        expected_counts=expected_projection_counts,
        expected_rows=expected_projection_rows,
    )
    legacy_manifest = validate_legacy_page_manifest(
        inputs.legacy_page_manifest,
        expected_page_counts=expected_page_counts,
        minimum_image_bytes=minimum_image_bytes,
    )
    gate_b_plan, gate_b = gate_b_loader(inputs.gate_b_plan)
    require(
        gate_b_plan.get("decision") == "READY_FOR_SHADOW_REPLAY",
        "Gate B is not ready for review-pack preparation",
    )
    gate_b_identity = gate_b.get("identity")
    require(isinstance(gate_b_identity, Mapping), "validated Gate B identity missing")
    gate_b_manifest = gate_b.get("manifest_by_page")
    require(isinstance(gate_b_manifest, Mapping), "validated Gate B page manifest missing")
    page3_row = gate_b_manifest.get(3)
    require(isinstance(page3_row, Mapping), "validated Gate B page 3 missing")
    require(
        page3_row.get("sha256") == EXPECTED_PAGE3_SHA256,
        "page 3 SHA binding mismatch",
    )

    temporary = inputs.output.with_name(inputs.output.name + ".tmp")
    require(not temporary.exists(), f"temporary output already exists: {temporary}")
    temporary.mkdir(parents=True)
    try:
        legacy_pages: list[dict[str, Any]] = []
        for row in legacy_manifest["rows"]:
            source = (
                inputs.legacy_page_root
                / row["label"]
                / f"page-{row['page_number']:03d}.img"
            )
            data, suffix = validate_image(
                source,
                expected_sha256=row["sha256"],
                expected_bytes=row["bytes"],
                expected_format=row["format"],
            )
            relative = (
                Path("images")
                / "legacy"
                / row["label"]
                / f"page-{row['page_number']:03d}{suffix}"
            )
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            legacy_pages.append(
                {
                    "kind": "legacy",
                    "source_page": row["label"],
                    "page_number": row["page_number"],
                    "sha256": row["sha256"],
                    "bytes": row["bytes"],
                    "image_format": row["format"],
                    "image_path": relative.as_posix(),
                    "card_id_prefix": (
                        f"{row['label']}:p{row['page_number']:03d}:c"
                    ),
                }
            )

        current_page3_source = inputs.current_pages_root / "page-003.img"
        page3_data = (
            current_page3_source.read_bytes()
            if current_page3_source.is_file()
            else b""
        )
        require(not current_page3_source.is_symlink(), "symlinked current page 3 forbidden")
        require(bool(page3_data), f"current page 3 is missing: {current_page3_source}")
        require(
            len(page3_data) == page3_row["bytes"],
            "current page 3 byte count mismatch",
        )
        require(
            sha256(page3_data).hexdigest() == EXPECTED_PAGE3_SHA256,
            "current page 3 SHA mismatch",
        )
        page3_format, page3_suffix = detect_image_format(page3_data)
        require(
            page3_format == page3_row["image_format"],
            "current page 3 format mismatch",
        )
        page3_relative = Path("images") / "current" / f"page-003{page3_suffix}"
        page3_destination = temporary / page3_relative
        page3_destination.parent.mkdir(parents=True, exist_ok=True)
        page3_destination.write_bytes(page3_data)
        page3 = {
            "kind": "current_page3",
            "source_page": "current",
            "page_number": 3,
            "sha256": EXPECTED_PAGE3_SHA256,
            "bytes": len(page3_data),
            "image_format": page3_format,
            "image_path": page3_relative.as_posix(),
            "card_id_prefix": "current:p003:c",
        }

        legacy_template = build_legacy_ledger_template(
            projection_rows,
            legacy_manifest,
        )
        hints = legacy_template["candidate_hints"]
        page3_template = {
            "schema_version": 1,
            "mode": "ALDI_WEEKLY_PAGE3_FRESH_SHADOW_EXTRACTION_V01",
            "page_number": 3,
            "page_sha256": EXPECTED_PAGE3_SHA256,
            "extraction_result": "pending_manual_visual_review",
            "shadow_only": True,
            "production_eligible": False,
            "candidate_creation_performed": False,
            "database_write_performed": False,
            "review_write_performed": False,
            "automatic_approval_performed": False,
            "automatic_publication_performed": False,
            "candidate_count": 0,
            "candidates": [],
            "instructions": [
                "Add one Review-only candidate per visually distinct in-scope page-3 card.",
                "Use stable current:p003:cNNN card IDs.",
                "Every candidate must include at least one review reason.",
                "Do not mark any row production-eligible or automatically approved/published.",
            ],
        }
        identity = {
            "commit_sha": inputs.commit_sha,
            "a21_projection_sha256": sha_file(inputs.projection),
            "legacy_page_manifest_sha256": legacy_manifest["manifest_sha256"],
            "legacy_page_set_sha256": legacy_manifest["page_set_sha256"],
            "gate_b_plan_sha256": EXPECTED_GATE_B_PLAN_SHA256,
            "gate_b_replay_fingerprint": gate_b_plan.get("replay_fingerprint"),
            "current_manifest_sha256": gate_b_identity.get("current_manifest_sha256"),
            "current_page3_sha256": EXPECTED_PAGE3_SHA256,
        }
        write_json(temporary / "legacy-card-ledger-template.json", legacy_template)
        write_json(
            temporary / "page3-fresh-shadow-extraction-template.json",
            page3_template,
        )
        write_json(temporary / "candidate-hints.json", hints)
        write_json(
            temporary / "review-index.json",
            {
                "schema_version": 1,
                "mode": MODE,
                "legacy_pages": legacy_pages,
                "current_page3": page3,
                "identity": identity,
            },
        )
        (temporary / "index.html").write_text(
            render_html(
                legacy_pages=legacy_pages,
                page3=page3,
                hints=hints,
                identity=identity,
            ),
            encoding="utf-8",
        )
        (temporary / "README.md").write_text(
            "# ALDI Gate D visual review pack\n\n"
            "Open `index.html` locally. This pack is for manual visual "
            "adjudication only.\n\n"
            "Complete `legacy-card-ledger-template.json` and "
            "`page3-fresh-shadow-extraction-template.json` in a separate "
            "controlled copy. The templates intentionally do not claim parity "
            "or extraction completion.\n",
            encoding="utf-8",
        )

        files: list[dict[str, Any]] = []
        for path in sorted(temporary.rglob("*")):
            if path.is_file() and path.name != "review-pack-manifest.json":
                files.append(
                    {
                        "path": path.relative_to(temporary).as_posix(),
                        "bytes": path.stat().st_size,
                        "sha256": sha_file(path),
                    }
                )
        manifest = {
            "schema_version": 1,
            "mode": MODE,
            "decision": DECISION,
            "issue_number": 215,
            "parent_issue_number": 165,
            "upstream_issue_numbers": [64, 191, 196, 200, 203, 208, 210],
            "identity": identity,
            "counts": {
                "legacy_page_count": len(legacy_pages),
                "legacy_current_page_count": sum(
                    row["source_page"] == "current" for row in legacy_pages
                ),
                "legacy_preview_page_count": sum(
                    row["source_page"] == "preview" for row in legacy_pages
                ),
                "target_candidate_hint_count": len(hints),
                "current_page3_count": 1,
                "automatic_assignments": 0,
                "completed_legacy_cards": 0,
                "completed_page3_candidates": 0,
            },
            "outputs": files,
            "outputs_sha256": canonical_sha(files),
            "safety": safety_contract(),
            "gate_c_ready": False,
            "production_eligible": False,
            "next_required_action": (
                "manual_visual_adjudication_then_fail_closed_verification"
            ),
        }
        write_json(temporary / "review-pack-manifest.json", manifest)
        temporary.replace(inputs.output)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--legacy-page-manifest", type=Path, required=True)
    parser.add_argument("--legacy-page-root", type=Path, required=True)
    parser.add_argument("--gate-b-plan", type=Path, required=True)
    parser.add_argument("--current-pages-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit-sha", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = create_review_pack(
        PackInputs(
            projection=args.projection,
            legacy_page_manifest=args.legacy_page_manifest,
            legacy_page_root=args.legacy_page_root,
            gate_b_plan=args.gate_b_plan,
            current_pages_root=args.current_pages_root,
            output=args.output,
            commit_sha=args.commit_sha,
        )
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
