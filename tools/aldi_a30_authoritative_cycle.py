from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MODE = "ALDI_A30_AUTHORITATIVE_CYCLE_ACQUISITION_V01"
SENSITIVE_KEYS = {
    "token", "signature", "sig", "policy", "key-pair-id",
    "x-amz-signature", "x-amz-credential", "x-amz-security-token",
}


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in SENSITIVE_KEYS:
            value = "<redacted>"
        query.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def image_format(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return None


def validate_plan(plan: dict[str, Any]) -> None:
    if plan.get("mode") != "ALDI_A30_AUTHORITATIVE_CYCLE_PLAN_V01":
        raise SystemExit("unexpected plan mode")
    sources = plan.get("sources") or {}
    if set(sources) != {"current", "preview"}:
        raise SystemExit("plan must contain current and preview")
    paths = []
    for label, row in sources.items():
        template = str(row.get("image_template") or "")
        if "{page}" not in template:
            raise SystemExit(f"{label} template lacks page token")
        parts = urlsplit(template)
        if parts.scheme != "https" or parts.netloc != "ipaper.ipapercms.dk":
            raise SystemExit(f"{label} template host is not allowlisted")
        path = str(row.get("source_path") or "")
        if not path.startswith("/aldi-nord/") or not path.endswith("/"):
            raise SystemExit(f"{label} source path invalid")
        paths.append(path)
    if paths[0] == paths[1]:
        raise SystemExit("current and preview source paths must differ")


def request_page(api: Any, template: str, page_number: int, minimum_bytes: int) -> tuple[dict[str, Any], bytes]:
    url = template.replace("{page}", str(page_number))
    try:
        response = api.get(
            url,
            timeout=120_000,
            fail_on_status_code=False,
            headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},
        )
        data = response.body()
        fmt = image_format(data)
        live = 200 <= response.status < 400 and fmt is not None and len(data) >= minimum_bytes
        row = {
            "page_number": page_number,
            "requested_url": redact_url(url),
            "final_url": redact_url(response.url),
            "status": response.status,
            "content_type": response.headers.get("content-type", ""),
            "bytes": len(data),
            "sha256": sha256(data).hexdigest(),
            "image_format": fmt or "",
            "live": live,
        }
        return row, data
    except Exception as exc:
        return {
            "page_number": page_number,
            "requested_url": redact_url(url),
            "live": False,
            "error": f"{type(exc).__name__}: {exc}",
        }, b""


def acquire_source(api: Any, label: str, row: dict[str, Any], out_dir: Path, limits: dict[str, Any]) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=False)
    max_pages = int(limits["max_pages"])
    minimum = int(limits["minimum_image_bytes"])
    terminal_need = int(limits["consecutive_terminal_failures"])
    pages: list[dict[str, Any]] = []
    terminal: list[dict[str, Any]] = []
    consecutive = 0
    for page_number in range(1, max_pages + terminal_need + 1):
        probe, data = request_page(api, row["image_template"], page_number, minimum)
        if probe["live"]:
            if consecutive:
                raise SystemExit(f"{label} source resumed after terminal failure at page {page_number}")
            path = out_dir / f"page-{page_number:03d}.img"
            path.write_bytes(data)
            pages.append({**probe, "path": str(path)})
        else:
            consecutive += 1
            terminal.append(probe)
            if consecutive >= terminal_need:
                break
    if not pages:
        raise SystemExit(f"{label} acquired zero pages")
    if len(terminal) < terminal_need:
        raise SystemExit(f"{label} terminal boundary not proven")
    expected = list(range(1, len(pages) + 1))
    actual = [int(page["page_number"]) for page in pages]
    if actual != expected:
        raise SystemExit(f"{label} page sequence gap")
    return {
        "label": label,
        "source_path": row["source_path"],
        "valid_from": row.get("valid_from"),
        "valid_to": row.get("valid_to"),
        "page_count": len(pages),
        "pages": pages,
        "terminal_probes": terminal[-terminal_need:],
        "state": "complete",
    }


def verify_old_preview(run_dir: Path, expected_count: int) -> list[Path]:
    manifest = json.loads((run_dir / "reports/page-image-manifest.json").read_text())
    rows = [row for row in manifest.get("rows", []) if row.get("label") == "preview"]
    if len(rows) != expected_count:
        raise SystemExit("old preview manifest count mismatch")
    result: list[Path] = []
    for row in sorted(rows, key=lambda value: int(value["page_number"])):
        page_number = int(row["page_number"])
        path = run_dir / "raw/page-images/preview" / f"page-{page_number:03d}.img"
        data = path.read_bytes()
        if sha256(data).hexdigest() != row["sha256"] or len(data) != int(row["bytes"]):
            raise SystemExit(f"old preview integrity mismatch page {page_number}")
        result.append(path)
    return result


DECODE_JS = """
async ({left,right}) => {
  async function decode(b64) {
    const blob = await (await fetch('data:image/jpeg;base64,' + b64)).blob();
    const bitmap = await createImageBitmap(blob);
    const canvas = document.createElement('canvas'); canvas.width=32; canvas.height=32;
    const ctx=canvas.getContext('2d',{willReadFrequently:true});
    ctx.drawImage(bitmap,0,0,32,32);
    const rgba=ctx.getImageData(0,0,32,32).data;
    const gray=[];
    for(let i=0;i<rgba.length;i+=4) gray.push(Math.round(0.299*rgba[i]+0.587*rgba[i+1]+0.114*rgba[i+2]));
    return {width:bitmap.width,height:bitmap.height,gray};
  }
  return {left:await decode(left),right:await decode(right)};
}
"""


def compare_pair(page: Any, left_path: Path, right_path: Path, thresholds: dict[str, Any], page_number: int) -> dict[str, Any]:
    left = left_path.read_bytes()
    right = right_path.read_bytes()
    decoded = page.evaluate(
        DECODE_JS,
        {"left": base64.b64encode(left).decode(), "right": base64.b64encode(right).decode()},
    )
    a = decoded["left"]["gray"]
    b = decoded["right"]["gray"]
    if len(a) != 1024 or len(b) != 1024:
        raise SystemExit("decoded vector length mismatch")
    diffs = [abs(int(x) - int(y)) for x, y in zip(a, b)]
    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)
    hamming = sum((x >= mean_a) != (y >= mean_b) for x, y in zip(a, b))
    mae = sum(diffs) / len(diffs)
    rms = math.sqrt(sum(diff * diff for diff in diffs) / len(diffs))
    ordered = sorted(diffs)
    p99 = ordered[min(len(ordered) - 1, math.ceil(len(ordered) * 0.99) - 1)]
    dimension_match = (
        decoded["left"]["width"] == decoded["right"]["width"]
        and decoded["left"]["height"] == decoded["right"]["height"]
    )
    visual_match = (
        dimension_match
        and hamming <= int(thresholds["max_hamming"])
        and mae <= float(thresholds["max_mae"])
        and rms <= float(thresholds["max_rms"])
        and p99 <= int(thresholds["max_p99"])
    )
    return {
        "page_number": page_number,
        "exact_bytes": sha256(left).hexdigest() == sha256(right).hexdigest(),
        "left_sha256": sha256(left).hexdigest(),
        "right_sha256": sha256(right).hexdigest(),
        "left_dimensions": [decoded["left"]["width"], decoded["left"]["height"]],
        "right_dimensions": [decoded["right"]["width"], decoded["right"]["height"]],
        "hamming": hamming,
        "mae": round(mae, 6),
        "rms": round(rms, 6),
        "p99": p99,
        "visual_match": visual_match,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--browser-executable", required=True, type=Path)
    parser.add_argument("--commit-sha", required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    validate_plan(plan)
    if not args.browser_executable.is_file():
        raise SystemExit("browser executable missing")
    args.output.mkdir(parents=True, exist_ok=False)
    pages_root = args.output / "pages"
    pages_root.mkdir()
    old_paths = verify_old_preview(Path(plan["old_preview_run"]), int(plan["old_preview_page_count"]))

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        api = playwright.request.new_context(
            extra_http_headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 Chrome/149 Safari/537.36",
                "Accept-Language": "de-DE,de;q=0.9",
            }
        )
        try:
            acquired = {
                label: acquire_source(api, label, row, pages_root / label, plan["limits"])
                for label, row in plan["sources"].items()
            }
        finally:
            api.dispose()

        browser = playwright.chromium.launch(
            executable_path=str(args.browser_executable),
            headless=True,
            args=["--disable-dev-shm-usage", "--disable-gpu"],
        )
        try:
            page = browser.new_page()
            current_paths = [Path(row["path"]) for row in acquired["current"]["pages"]]
            required = int(plan["rollover"]["required_pages"])
            comparisons = []
            if len(current_paths) == required and len(old_paths) == required:
                comparisons = [
                    compare_pair(page, old_paths[index], current_paths[index], plan["rollover"], index + 1)
                    for index in range(required)
                ]
        finally:
            browser.close()

    rollover_match = (
        len(comparisons) == int(plan["rollover"]["required_pages"])
        and all(row["visual_match"] for row in comparisons)
    )
    source_distinct = acquired["current"]["source_path"] != acquired["preview"]["source_path"]
    passed = (
        acquired["current"]["page_count"] == int(plan["rollover"]["required_pages"])
        and acquired["preview"]["page_count"] > 0
        and rollover_match
        and source_distinct
    )
    for label in ("current", "preview"):
        for row in acquired[label]["pages"]:
            row["path"] = str(Path(row["path"]).relative_to(args.output))

    report = {
        "schema_version": 1,
        "mode": MODE,
        "commit_sha": args.commit_sha,
        "plan_sha256": sha256(args.plan.read_bytes()).hexdigest(),
        "source_discovery_commit": plan["source_discovery_commit"],
        "source_discovery_run_id": plan["source_discovery_run_id"],
        "sources": acquired,
        "rollover": {
            "required_pages": plan["rollover"]["required_pages"],
            "matched_pages": sum(row["visual_match"] for row in comparisons),
            "all_pages_match": rollover_match,
            "comparisons": comparisons,
        },
        "source_roots_distinct": source_distinct,
        "state": "new_authoritative_cycle_captured" if passed else "authoritative_cycle_blocked",
        "result": "pass" if passed else "blocked",
        "page_acquisition_performed": True,
        "rollover_comparison_performed": True,
        "third_party_catalog_sources_used": False,
        "production_database_write": False,
        "production_deployment": False,
        "collector_executed": False,
        "automatic_approval": False,
        "automatic_publication": False,
    }
    (args.output / "authoritative-cycle-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(f"CURRENT_PAGE_COUNT={acquired['current']['page_count']}")
    print(f"PREVIEW_PAGE_COUNT={acquired['preview']['page_count']}")
    print(f"ROLLOVER_MATCHED_PAGES={report['rollover']['matched_pages']}")
    print(f"ROLLOVER_MATCH_41_OF_41={str(rollover_match).lower()}")
    print(f"RESULT={'ALDI_A30_AUTHORITATIVE_CYCLE_PASS' if passed else 'ALDI_A30_AUTHORITATIVE_CYCLE_REVIEW_REQUIRED'}")
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main())
