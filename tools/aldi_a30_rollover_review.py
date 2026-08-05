from __future__ import annotations

import argparse
import base64
from collections import defaultdict
from hashlib import sha256
from html import escape
import json
import math
from pathlib import Path
import shutil
from typing import Any


MODE = "ALDI_A30_ROLLOVER_REVIEW_ANALYSIS_V01"
MAX_CHANGED_CROSS_PAIRS = 64


def image_format(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return None


def image_mime(data: bytes) -> str:
    return {
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }.get(image_format(data), "application/octet-stream")


def image_extension(data: bytes) -> str:
    return {
        "jpeg": ".jpg",
        "png": ".png",
        "webp": ".webp",
    }.get(image_format(data), ".img")


def verify_old_preview(run_dir: Path, expected_count: int) -> list[Path]:
    manifest_path = run_dir / "reports/page-image-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = [row for row in manifest.get("rows", []) if row.get("label") == "preview"]
    if len(rows) != expected_count:
        raise SystemExit("old preview manifest count mismatch")
    result: list[Path] = []
    for row in sorted(rows, key=lambda value: int(value["page_number"])):
        page_number = int(row["page_number"])
        path = run_dir / "raw/page-images/preview" / f"page-{page_number:03d}.img"
        data = path.read_bytes()
        if sha256(data).hexdigest() != row["sha256"]:
            raise SystemExit(f"old preview SHA256 mismatch page {page_number}")
        if len(data) != int(row["bytes"]):
            raise SystemExit(f"old preview byte-size mismatch page {page_number}")
        result.append(path)
    return result


def current_paths_from_report(evidence: Path, report: dict[str, Any]) -> list[Path]:
    rows = report["sources"]["current"]["pages"]
    ordered = sorted(rows, key=lambda row: int(row["page_number"]))
    expected = list(range(1, len(ordered) + 1))
    actual = [int(row["page_number"]) for row in ordered]
    if actual != expected:
        raise SystemExit("current report page sequence is not contiguous")
    result: list[Path] = []
    for row in ordered:
        path = evidence / str(row["path"])
        data = path.read_bytes()
        if sha256(data).hexdigest() != row["sha256"]:
            raise SystemExit(f"current SHA256 mismatch page {row['page_number']}")
        if len(data) != int(row["bytes"]):
            raise SystemExit(f"current byte-size mismatch page {row['page_number']}")
        result.append(path)
    return result


def classify_exact_rollover(
    old_paths: list[Path],
    current_paths: list[Path],
) -> dict[str, Any]:
    old_by_sha: dict[str, list[int]] = defaultdict(list)
    new_by_sha: dict[str, list[int]] = defaultdict(list)
    for page_number, path in enumerate(old_paths, start=1):
        old_by_sha[sha256(path.read_bytes()).hexdigest()].append(page_number)
    for page_number, path in enumerate(current_paths, start=1):
        new_by_sha[sha256(path.read_bytes()).hexdigest()].append(page_number)

    same_position: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = []
    old_only: list[int] = []
    new_only: list[int] = []
    duplicate_groups: list[dict[str, Any]] = []
    content_set_matched = 0

    for digest in sorted(set(old_by_sha) | set(new_by_sha)):
        old_pages = list(old_by_sha.get(digest, []))
        new_pages = list(new_by_sha.get(digest, []))
        if len(old_pages) > 1 or len(new_pages) > 1:
            duplicate_groups.append({
                "sha256": digest,
                "old_pages": old_pages,
                "new_pages": new_pages,
            })

        common_positions = sorted(set(old_pages) & set(new_pages))
        for page_number in common_positions:
            same_position.append({
                "old_page": page_number,
                "new_page": page_number,
                "sha256": digest,
            })
            old_pages.remove(page_number)
            new_pages.remove(page_number)

        paired = min(len(old_pages), len(new_pages))
        content_set_matched += len(common_positions) + paired
        for old_page, new_page in zip(old_pages[:paired], new_pages[:paired]):
            moved.append({
                "old_page": old_page,
                "new_page": new_page,
                "sha256": digest,
            })
        old_only.extend(old_pages[paired:])
        new_only.extend(new_pages[paired:])

    return {
        "exact_positional_matches": sorted(same_position, key=lambda row: row["old_page"]),
        "exact_positional_matched_pages": len(same_position),
        "content_set_matched_pages": content_set_matched,
        "moved_pages": sorted(moved, key=lambda row: (row["old_page"], row["new_page"])),
        "old_only_pages": sorted(old_only),
        "new_only_pages": sorted(new_only),
        "duplicate_content_groups": duplicate_groups,
    }


DECODE_JS = """
async ({left,right,leftType,rightType}) => {
  async function decode(b64, mime) {
    const blob = await (await fetch(`data:${mime};base64,${b64}`)).blob();
    const bitmap = await createImageBitmap(blob);
    const canvas = document.createElement('canvas');
    canvas.width=32; canvas.height=32;
    const ctx=canvas.getContext('2d',{willReadFrequently:true});
    ctx.drawImage(bitmap,0,0,32,32);
    const rgba=ctx.getImageData(0,0,32,32).data;
    const gray=[];
    for(let i=0;i<rgba.length;i+=4) {
      gray.push(Math.round(0.299*rgba[i]+0.587*rgba[i+1]+0.114*rgba[i+2]));
    }
    return {width:bitmap.width,height:bitmap.height,gray};
  }
  return {
    left:await decode(left,leftType),
    right:await decode(right,rightType),
  };
}
"""


def compare_pair(
    page: Any,
    left_path: Path,
    right_path: Path,
    thresholds: dict[str, Any],
    old_page: int,
    new_page: int,
) -> dict[str, Any]:
    left = left_path.read_bytes()
    right = right_path.read_bytes()
    decoded = page.evaluate(
        DECODE_JS,
        {
            "left": base64.b64encode(left).decode(),
            "right": base64.b64encode(right).decode(),
            "leftType": image_mime(left),
            "rightType": image_mime(right),
        },
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
    left_dimensions = [decoded["left"]["width"], decoded["left"]["height"]]
    right_dimensions = [decoded["right"]["width"], decoded["right"]["height"]]
    dimension_penalty = 10.0 if left_dimensions != right_dimensions else 0.0
    score = round(
        dimension_penalty
        + hamming / 1024.0
        + mae / 255.0
        + rms / 255.0
        + p99 / 255.0,
        9,
    )
    return {
        "old_page": old_page,
        "new_page": new_page,
        "left_sha256": sha256(left).hexdigest(),
        "right_sha256": sha256(right).hexdigest(),
        "left_dimensions": left_dimensions,
        "right_dimensions": right_dimensions,
        "hamming": hamming,
        "mae": round(mae, 6),
        "rms": round(rms, 6),
        "p99": p99,
        "candidate_score": score,
        "within_strict_visual_threshold": (
            left_dimensions == right_dimensions
            and hamming <= int(thresholds["max_hamming"])
            and mae <= float(thresholds["max_mae"])
            and rms <= float(thresholds["max_rms"])
            and p99 <= int(thresholds["max_p99"])
        ),
    }


def compare_changed_candidates(
    browser_page: Any,
    old_paths: list[Path],
    current_paths: list[Path],
    old_pages: list[int],
    new_pages: list[int],
    thresholds: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    pair_count = len(old_pages) * len(new_pages)
    if pair_count > MAX_CHANGED_CROSS_PAIRS:
        return [], True
    candidates = [
        compare_pair(
            browser_page,
            old_paths[old_page - 1],
            current_paths[new_page - 1],
            thresholds,
            old_page,
            new_page,
        )
        for old_page in old_pages
        for new_page in new_pages
    ]
    return sorted(
        candidates,
        key=lambda row: (row["candidate_score"], row["old_page"], row["new_page"]),
    ), False


def write_manual_review_bundle(
    evidence: Path,
    old_paths: list[Path],
    current_paths: list[Path],
    exact: dict[str, Any],
    candidate_pairs: list[dict[str, Any]],
    candidate_metrics_skipped: bool,
) -> dict[str, Any]:
    review_root = evidence / "manual-review"
    if review_root.exists():
        raise SystemExit("manual-review output already exists")
    old_root = review_root / "old-preview"
    new_root = review_root / "new-current"
    old_root.mkdir(parents=True)
    new_root.mkdir(parents=True)

    def copy_pages(
        pages: list[int],
        paths: list[Path],
        destination_root: Path,
        label: str,
    ) -> list[dict[str, Any]]:
        rows = []
        for page_number in pages:
            source = paths[page_number - 1]
            data = source.read_bytes()
            destination = destination_root / (
                f"page-{page_number:03d}{image_extension(data)}"
            )
            shutil.copyfile(source, destination)
            rows.append({
                "page_number": page_number,
                "label": label,
                "path": destination.relative_to(evidence).as_posix(),
                "sha256": sha256(data).hexdigest(),
                "bytes": len(data),
            })
        return rows

    old_files = copy_pages(
        exact["old_only_pages"],
        old_paths,
        old_root,
        "old_preview",
    )
    new_files = copy_pages(
        exact["new_only_pages"],
        current_paths,
        new_root,
        "new_current",
    )
    manual_required = bool(old_files or new_files)
    summary = {
        "schema_version": 1,
        "mode": MODE,
        "classification": (
            "manual_review_required" if manual_required else "no_manual_review"
        ),
        "exact_positional_matched_pages": exact["exact_positional_matched_pages"],
        "content_set_matched_pages": exact["content_set_matched_pages"],
        "moved_pages": exact["moved_pages"],
        "old_only_pages": exact["old_only_pages"],
        "new_only_pages": exact["new_only_pages"],
        "duplicate_content_groups": exact["duplicate_content_groups"],
        "old_preview_files": old_files,
        "new_current_files": new_files,
        "candidate_pairs": candidate_pairs,
        "candidate_metrics_skipped": candidate_metrics_skipped,
        "automatic_promotion_allowed": False,
    }
    (review_root / "manual-review.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    moved_rows = "".join(
        "<tr>"
        f"<td>{row['old_page']}</td><td>{row['new_page']}</td>"
        f"<td><code>{escape(row['sha256'])}</code></td>"
        "</tr>"
        for row in exact["moved_pages"]
    ) or "<tr><td colspan='3'>None</td></tr>"

    def image_figures(rows: list[dict[str, Any]], title: str) -> str:
        return "".join(
            "<figure>"
            f"<figcaption>{escape(title)} {row['page_number']}</figcaption>"
            f"<img src='{escape(Path(row['path']).relative_to('manual-review').as_posix())}' "
            f"alt='{escape(title)} {row['page_number']}'>"
            "</figure>"
            for row in rows
        ) or "<p>None</p>"

    pair_rows = "".join(
        "<tr>"
        f"<td>{row['old_page']}</td><td>{row['new_page']}</td>"
        f"<td>{row['candidate_score']}</td><td>{row['hamming']}</td>"
        f"<td>{row['mae']}</td><td>{row['rms']}</td><td>{row['p99']}</td>"
        "</tr>"
        for row in candidate_pairs
    ) or "<tr><td colspan='7'>None</td></tr>"

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ALDI rollover manual review</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1400px;margin:2rem auto;padding:0 1rem}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:1rem}}
figure{{margin:0 0 1rem;border:1px solid #bbb;padding:.5rem}}
img{{max-width:100%;height:auto;display:block}}
table{{border-collapse:collapse;width:100%;margin-bottom:1.5rem}}
th,td{{border:1px solid #bbb;padding:.4rem;text-align:left}}
code{{font-size:.8rem;word-break:break-all}}
</style>
</head>
<body>
<h1>ALDI rollover manual review</h1>
<p>The strict 41/41 automatic-promotion gate remains unchanged.</p>
<ul>
<li>Exact positional matches: {exact['exact_positional_matched_pages']}</li>
<li>Exact content-set matches: {exact['content_set_matched_pages']}</li>
<li>Old-only pages: {escape(', '.join(map(str, exact['old_only_pages'])) or 'none')}</li>
<li>New-only pages: {escape(', '.join(map(str, exact['new_only_pages'])) or 'none')}</li>
</ul>
<h2>Moved identical pages</h2>
<table><thead><tr><th>Old page</th><th>New page</th><th>SHA256</th></tr></thead>
<tbody>{moved_rows}</tbody></table>
<div class="grid">
<section><h2>Old preview pages</h2>{image_figures(old_files, 'Old preview page')}</section>
<section><h2>New current pages</h2>{image_figures(new_files, 'New current page')}</section>
</div>
<h2>Candidate pair metrics</h2>
<p>Skipped because of pair limit: {str(candidate_metrics_skipped).lower()}</p>
<table><thead><tr><th>Old</th><th>New</th><th>Score</th><th>Hamming</th><th>MAE</th><th>RMS</th><th>p99</th></tr></thead>
<tbody>{pair_rows}</tbody></table>
</body>
</html>
"""
    (review_root / "index.html").write_text(html, encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--browser-executable", required=True, type=Path)
    args = parser.parse_args()

    report_path = args.evidence / "authoritative-cycle-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if report.get("mode") != "ALDI_A30_AUTHORITATIVE_CYCLE_ACQUISITION_V01":
        raise SystemExit("unexpected authoritative-cycle report mode")
    if not args.browser_executable.is_file():
        raise SystemExit("browser executable missing")

    old_paths = verify_old_preview(
        Path(plan["old_preview_run"]),
        int(plan["old_preview_page_count"]),
    )
    current_paths = current_paths_from_report(args.evidence, report)
    exact = classify_exact_rollover(old_paths, current_paths)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(args.browser_executable),
            headless=True,
            args=["--disable-dev-shm-usage", "--disable-gpu"],
        )
        try:
            browser_page = browser.new_page()
            candidate_pairs, candidate_metrics_skipped = compare_changed_candidates(
                browser_page,
                old_paths,
                current_paths,
                exact["old_only_pages"],
                exact["new_only_pages"],
                plan["rollover"],
            )
        finally:
            browser.close()

    manual_review = write_manual_review_bundle(
        args.evidence,
        old_paths,
        current_paths,
        exact,
        candidate_pairs,
        candidate_metrics_skipped,
    )
    positional_visual = int(report["rollover"]["matched_pages"])
    analysis = {
        "schema_version": 1,
        "mode": MODE,
        "positional_visual_matched_pages": positional_visual,
        "exact_positional_matched_pages": exact["exact_positional_matched_pages"],
        "content_set_matched_pages": exact["content_set_matched_pages"],
        "moved_pages": exact["moved_pages"],
        "old_only_pages": exact["old_only_pages"],
        "new_only_pages": exact["new_only_pages"],
        "duplicate_content_groups": exact["duplicate_content_groups"],
        "manual_review_required": (
            manual_review["classification"] == "manual_review_required"
        ),
        "manual_review_path": "manual-review/manual-review.json",
        "candidate_pairs": candidate_pairs,
        "candidate_metrics_skipped": candidate_metrics_skipped,
        "strict_41_of_41_gate_unchanged": True,
        "automatic_promotion_allowed": report.get("result") == "pass",
    }
    report["schema_version"] = 2
    report["rollover_analysis"] = analysis
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"ROLLOVER_POSITIONAL_MATCHED_PAGES={positional_visual}")
    print(
        "ROLLOVER_CONTENT_SET_MATCHED_PAGES="
        f"{exact['content_set_matched_pages']}"
    )
    print(
        "ROLLOVER_MOVED_PAGES="
        + ",".join(
            f"{row['old_page']}->{row['new_page']}"
            for row in exact["moved_pages"]
        )
    )
    print(
        "ROLLOVER_OLD_ONLY_PAGES="
        + ",".join(map(str, exact["old_only_pages"]))
    )
    print(
        "ROLLOVER_NEW_ONLY_PAGES="
        + ",".join(map(str, exact["new_only_pages"]))
    )
    print(
        "MANUAL_REVIEW_REQUIRED="
        f"{str(analysis['manual_review_required']).lower()}"
    )
    print("ROLLOVER_REVIEW_ANALYSIS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
