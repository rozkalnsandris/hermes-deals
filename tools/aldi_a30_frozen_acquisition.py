#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
from typing import Any, Mapping

AUDIT_NAME = "aldi-a30-frozen-acquisition-v1"
EXPECTED_A21_ARCHIVE_SHA256 = (
    "fa16df4db701e90f38bea0387a278750415ba03628f1fe1cc34ffb2833f2985d"
)
EXPECTED_A21_PROJECTION_SHA256 = (
    "64699b7ede52dcaa5b85f3306426f3b90399dd037209621a38bacd166161d5ea"
)
EXPECTED_A21_ROWS = 519
EXPECTED_SCOPE_COUNTS = {
    "in_scope": 387,
    "out_of_scope": 119,
    "review": 13,
}
EXPECTED_PUBLICATION_COUNTS = {
    "auto_candidate": 346,
    "blocked_out_of_scope": 119,
    "review_required": 54,
}
EXPECTED_PAGE_COUNTS = {"current": 49, "preview": 41}


class AldiA30Error(RuntimeError):
    pass


def sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _safe_member(member: tarfile.TarInfo) -> bool:
    path = PurePosixPath(member.name)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and not member.issym()
        and not member.islnk()
        and not member.isdev()
        and (member.isdir() or member.isfile())
    )


def _manifest_rows(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            expected, relative = raw_line.split(None, 1)
        except ValueError as exc:
            raise AldiA30Error(f"invalid manifest line: {raw_line!r}") from exc
        relative = relative.strip().removeprefix("*").removeprefix("./")
        if len(expected) != 64 or not relative:
            raise AldiA30Error(f"invalid manifest entry: {raw_line!r}")
        rows.append((expected, relative))
    if not rows:
        raise AldiA30Error("A2.1 manifest is empty")
    return rows


def verify_a21_archive(
    archive: Path,
    destination: Path,
    *,
    expected_archive_sha256: str = EXPECTED_A21_ARCHIVE_SHA256,
    expected_projection_sha256: str = EXPECTED_A21_PROJECTION_SHA256,
) -> tuple[Path, dict[str, Any]]:
    archive = archive.resolve()
    destination = destination.resolve()
    if not archive.is_file():
        raise AldiA30Error(f"A2.1 archive is missing: {archive}")
    actual_archive_sha256 = sha_file(archive)
    if actual_archive_sha256 != expected_archive_sha256:
        raise AldiA30Error(
            "A2.1 archive SHA mismatch: "
            f"expected={expected_archive_sha256} actual={actual_archive_sha256}"
        )

    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        unsafe = [member.name for member in members if not _safe_member(member)]
        if unsafe:
            raise AldiA30Error(f"unsafe A2.1 archive members: {unsafe[:10]}")
        roots = {
            PurePosixPath(member.name).parts[0]
            for member in members
            if member.name
        }
        if len(roots) != 1:
            raise AldiA30Error(
                f"A2.1 archive must contain one root, got {sorted(roots)}"
            )
        root_name = next(iter(roots))
        for member in members:
            target = (destination / member.name).resolve()
            if destination != target and destination not in target.parents:
                raise AldiA30Error(f"unsafe extraction target: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise AldiA30Error(f"cannot read archive member: {member.name}")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)

    root = destination / root_name
    manifest = root / "manifest.sha256"
    if not manifest.is_file():
        raise AldiA30Error("A2.1 manifest.sha256 is missing")
    entries = _manifest_rows(manifest)
    failures: list[dict[str, str]] = []
    for expected, relative in entries:
        path = (root / relative).resolve()
        if root != path and root not in path.parents:
            failures.append({"path": relative, "reason": "outside_root"})
        elif not path.is_file():
            failures.append({"path": relative, "reason": "missing"})
        else:
            actual = sha_file(path)
            if actual != expected:
                failures.append(
                    {
                        "path": relative,
                        "reason": "sha256_mismatch",
                        "expected": expected,
                        "actual": actual,
                    }
                )
    if failures:
        raise AldiA30Error(f"A2.1 manifest failures: {failures[:10]}")

    projection = root / "reports" / "a21-adjudicated-projection.jsonl"
    summary_path = root / "reports" / "a21-summary.json"
    if not projection.is_file() or not summary_path.is_file():
        raise AldiA30Error("required A2.1 reports are missing")
    projection_sha256 = sha_file(projection)
    if projection_sha256 != expected_projection_sha256:
        raise AldiA30Error(
            "A2.1 projection SHA mismatch: "
            f"expected={expected_projection_sha256} actual={projection_sha256}"
        )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if (
        summary.get("projection_rows") != EXPECTED_A21_ROWS
        or summary.get("scope_counts") != EXPECTED_SCOPE_COUNTS
        or summary.get("publication_counts") != EXPECTED_PUBLICATION_COUNTS
    ):
        raise AldiA30Error("A2.1 summary contract drift")

    return root, {
        "archive_sha256": actual_archive_sha256,
        "archive_member_count": len(members),
        "manifest_entry_count": len(entries),
        "projection_sha256": projection_sha256,
        "summary_sha256": sha_file(summary_path),
        "projection_rows": summary["projection_rows"],
        "scope_counts": summary["scope_counts"],
        "publication_counts": summary["publication_counts"],
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AldiA30Error(f"invalid JSON: {path}") from exc


def derive_source_plan(root: Path) -> dict[str, Any]:
    matches = sorted(root.rglob("reports/prospect-links.json"))
    if len(matches) != 1:
        raise AldiA30Error(
            f"expected one frozen prospect-links.json, got {len(matches)}"
        )
    source_path = matches[0]
    payload = _load_json(source_path)
    expected = {
        "current": ("prospect-current", 49, "2026cw31"),
        "preview": ("prospect-preview", 41, "2026cw32"),
    }
    sources: dict[str, Any] = {}

    for label, (source_key, page_count, week_token) in expected.items():
        item = payload.get(source_key) if isinstance(payload, Mapping) else None
        if not isinstance(item, Mapping):
            raise AldiA30Error(f"missing frozen source: {source_key}")
        urls = [str(value) for value in (item.get("all_urls") or [])]
        magazine_urls = sorted(
            {
                url
                for url in urls
                if url.startswith("https://magazine.aldi-nord.de/")
                and url.endswith("/")
            }
        )
        if len(magazine_urls) != 1:
            raise AldiA30Error(
                f"{label}: expected one magazine URL, got {magazine_urls}"
            )

        image_urls: dict[int, str] = {}
        bases: set[str] = set()
        for url in urls:
            prefix, marker, page_text = url.partition("?PageNumber=")
            if (
                not marker
                or not prefix.startswith("https://ipaper.ipapercms.dk/")
                or not prefix.endswith("/Image.ashx")
            ):
                continue
            try:
                page = int(page_text)
            except ValueError:
                continue
            image_urls[page] = url
            bases.add(prefix.rsplit("/", 1)[0] + "/")
        if sorted(image_urls) != list(range(1, page_count + 1)):
            raise AldiA30Error(f"{label}: frozen page sequence mismatch")
        if len(bases) != 1:
            raise AldiA30Error(f"{label}: frozen iPaper base is ambiguous")
        base = next(iter(bases))
        if week_token not in magazine_urls[0] or week_token not in base:
            raise AldiA30Error(f"{label}: frozen week token mismatch")

        sources[label] = {
            "source_key": source_key,
            "week_token": week_token,
            "magazine_url": magazine_urls[0],
            "ipaper_base_url": base,
            "page_count": page_count,
            "image_urls": [
                image_urls[page] for page in range(1, page_count + 1)
            ],
        }

    return {
        "strategy": "exact_urls_from_frozen_a0a1_official_prospect_discovery",
        "prospect_links_sha256": sha_file(source_path),
        "sources": sources,
        "total_expected_pages": sum(EXPECTED_PAGE_COUNTS.values()),
        "viewer_html_required_for_parity": False,
    }


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise AldiA30Error(f"required TSV is missing: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def validate_viewer_attempts(path: Path) -> dict[str, Any]:
    rows = read_tsv(path)
    expected = {
        (label, kind)
        for label in EXPECTED_PAGE_COUNTS
        for kind in ("magazine", "ipaper")
    }
    observed = {(row.get("label", ""), row.get("viewer_kind", "")) for row in rows}
    if observed != expected:
        raise AldiA30Error(
            f"viewer attempt set mismatch: expected={sorted(expected)} "
            f"observed={sorted(observed)}"
        )
    return {
        "attempt_count": len(rows),
        "http_ok_count": sum(
            str(row.get("http_ok", "")).casefold() == "true" for row in rows
        ),
        "statuses": {
            f"{row['label']}:{row['viewer_kind']}": {
                "http_ok": str(row.get("http_ok", "")).casefold() == "true",
                "http_code": row.get("http_code"),
                "url": row.get("url"),
            }
            for row in rows
        },
        "viewer_html_required_for_parity": False,
        "expired_viewer_is_fatal": False,
    }


def validate_page_images(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    rows = payload.get("rows") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        raise AldiA30Error("page-image manifest rows are missing")
    expected = {
        (label, page)
        for label, page_count in EXPECTED_PAGE_COUNTS.items()
        for page in range(1, page_count + 1)
    }
    observed: set[tuple[str, int]] = set()
    compact_rows: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise AldiA30Error("page-image manifest row is invalid")
        label = str(raw.get("label") or "")
        try:
            page = int(raw.get("page_number"))
            size = int(raw.get("bytes"))
        except (TypeError, ValueError) as exc:
            raise AldiA30Error("page-image numeric field is invalid") from exc
        sha = str(raw.get("sha256") or "")
        image_format = str(raw.get("format") or "")
        pair = (label, page)
        if pair in observed:
            raise AldiA30Error(f"duplicate frozen page image: {pair}")
        if pair not in expected:
            raise AldiA30Error(f"unexpected frozen page image: {pair}")
        if len(sha) != 64 or size < 10_000 or image_format == "unknown":
            raise AldiA30Error(f"invalid frozen page image: {pair}")
        observed.add(pair)
        compact_rows.append(
            {
                "label": label,
                "page_number": page,
                "sha256": sha,
                "bytes": size,
                "format": image_format,
            }
        )
    if observed != expected:
        missing = sorted(expected - observed)
        raise AldiA30Error(f"frozen page images are incomplete: {missing[:10]}")
    compact_rows.sort(key=lambda row: (row["label"], row["page_number"]))
    return {
        "total_images": len(compact_rows),
        "counts_by_label": {
            label: sum(row["label"] == label for row in compact_rows)
            for label in EXPECTED_PAGE_COUNTS
        },
        "total_bytes": sum(row["bytes"] for row in compact_rows),
        "manifest_sha256": sha_file(path),
        "page_set_sha256": sha256(
            json.dumps(
                compact_rows, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
    }


def selected_pdfs(path: Path) -> dict[str, dict[str, Any]]:
    rows = read_tsv(path)
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("selected", "")).casefold() != "true":
            continue
        label = row.get("label", "")
        selected[label] = {
            "url": row.get("url"),
            "sha256": row.get("sha256"),
            "bytes": int(row.get("bytes") or 0),
        }
    return selected


def build_capability_summary(
    *,
    a21: Mapping[str, Any],
    source_plan: Mapping[str, Any],
    viewers: Mapping[str, Any],
    images: Mapping[str, Any],
    pdf_attempts_path: Path,
    pdf_text_summary_path: Path,
) -> dict[str, Any]:
    pdfs = selected_pdfs(pdf_attempts_path)
    text_summary = _load_json(pdf_text_summary_path)
    documents = (
        text_summary.get("documents", {})
        if isinstance(text_summary, Mapping)
        else {}
    )
    checks: dict[str, Any] = {}
    for label, expected_pages in EXPECTED_PAGE_COUNTS.items():
        document = documents.get(label) if isinstance(documents, Mapping) else None
        document = document if isinstance(document, Mapping) else {}
        page_count = document.get("page_count")
        pages_with_text = int(document.get("pages_with_any_text") or 0)
        checks[label] = {
            "expected_pages": expected_pages,
            "official_page_images": images["counts_by_label"][label],
            "page_images_complete": (
                images["counts_by_label"][label] == expected_pages
            ),
            "pdf_accessible": label in pdfs,
            "pdf_page_count": page_count,
            "pdf_page_count_matches_images": page_count == expected_pages,
            "pages_with_any_text": pages_with_text,
            "text_page_coverage_ratio": (
                pages_with_text / expected_pages if expected_pages else 0.0
            ),
        }

    all_images_complete = all(
        check["page_images_complete"] for check in checks.values()
    )
    all_pdfs_accessible = all(
        check["pdf_accessible"] for check in checks.values()
    )
    all_pdf_counts_match = all(
        check["pdf_page_count_matches_images"] for check in checks.values()
    )
    text_coverage_good = all(
        check["text_page_coverage_ratio"] >= 0.80
        for check in checks.values()
    )
    parity_matcher_ready = (
        all_images_complete
        and all_pdfs_accessible
        and all_pdf_counts_match
        and text_coverage_good
    )

    return {
        "schema_version": 1,
        "audit": AUDIT_NAME,
        "strategy": "official_pinned_flipbook_acquisition_capability_v1",
        "input_a21_projection_sha256": a21["projection_sha256"],
        "input_a21_rows": a21["projection_rows"],
        "input_a21_scope_counts": a21["scope_counts"],
        "input_a21_publication_counts": a21["publication_counts"],
        "expected_total_pages": source_plan["total_expected_pages"],
        "official_page_images_acquired": images["total_images"],
        "viewer_http_ok_count": viewers["http_ok_count"],
        "viewer_attempt_count": viewers["attempt_count"],
        "viewer_html_required_for_parity": False,
        "expired_viewer_is_fatal": False,
        "pdf_text_backend": (
            text_summary.get("backend", "none")
            if isinstance(text_summary, Mapping)
            else "none"
        ),
        "checks": checks,
        "all_images_complete": all_images_complete,
        "all_pdfs_accessible": all_pdfs_accessible,
        "all_pdf_page_counts_match": all_pdf_counts_match,
        "text_coverage_good": text_coverage_good,
        "parity_matcher_ready": parity_matcher_ready,
        "acquisition_gate_passed": all_images_complete,
        "result": "pass" if all_images_complete else "blocked",
        "next_gate": (
            "A3.1 deterministic offer-to-page matching plus reverse page "
            "coverage, still no production writes"
            if parity_matcher_ready
            else
            "A3.1 image-assisted text recovery capability gate before "
            "matching, still no production writes"
        ),
        "shadow_only": True,
        "production_eligible": False,
        "production_apply_authorized": False,
        "database_write_performed": False,
        "deployment_performed": False,
        "collector_executed": False,
    }


def run_audit(
    *,
    archive: Path,
    page_manifest: Path,
    viewer_attempts: Path,
    pdf_attempts: Path,
    pdf_text_summary: Path,
    output: Path,
    commit_sha: str,
) -> dict[str, Any]:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    root, a21 = verify_a21_archive(archive, output / "input")
    source_plan = derive_source_plan(root)
    viewers = validate_viewer_attempts(viewer_attempts)
    images = validate_page_images(page_manifest)
    summary = build_capability_summary(
        a21=a21,
        source_plan=source_plan,
        viewers=viewers,
        images=images,
        pdf_attempts_path=pdf_attempts,
        pdf_text_summary_path=pdf_text_summary,
    )
    summary["commit_sha"] = commit_sha
    atomic_json(output / "a21-integrity.json", a21)
    atomic_json(output / "frozen-source-plan.json", source_plan)
    atomic_json(output / "viewer-capability.json", viewers)
    atomic_json(output / "page-image-capability.json", images)
    atomic_json(output / "audit-summary.json", summary)
    artifacts = [
        {
            "path": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha_file(path),
        }
        for path in sorted(output.iterdir())
        if path.is_file() and not path.is_symlink()
    ]
    atomic_json(
        output / "artifact-manifest.json",
        {
            "audit": AUDIT_NAME,
            "commit_sha": commit_sha,
            "files": artifacts,
            "production_apply_authorized": False,
        },
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline ALDI A3.0 frozen acquisition audit"
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--page-manifest", type=Path, required=True)
    parser.add_argument("--viewer-attempts", type=Path, required=True)
    parser.add_argument("--pdf-attempts", type=Path, required=True)
    parser.add_argument("--pdf-text-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit-sha", required=True)
    args = parser.parse_args()
    try:
        result = run_audit(
            archive=args.archive,
            page_manifest=args.page_manifest,
            viewer_attempts=args.viewer_attempts,
            pdf_attempts=args.pdf_attempts,
            pdf_text_summary=args.pdf_text_summary,
            output=args.output,
            commit_sha=args.commit_sha,
        )
    except (AldiA30Error, OSError, tarfile.TarError) as exc:
        print(f"ERROR|{exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["result"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
