"""Read-only publisher-only details bound to an immutable Netto Publitas capture.

This does not create retailer SKU links, offer ownership, pricing, or Review writes.
Only the separately captured, receipt-pinned 5659 publication can supply clicks.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re

from app.netto_booklet_review_scan import scan_netto_review_candidates

# Owner-authorized, independently SHA-verified #1123 retention receipts.
# New campaigns require their own independently verified capture/receipt gate.
_TRUSTED_PUBLICATIONS = {
    "hz45_hasb": {
        "store": "5659",
        "group": "regionale-hz",
        "publication_sha256": "a72414e732435504d7524a9bb707a069753f600f31638118f9f947e425236c45",
        "receipt_sha256": "ca579d8500771cdf58a475a11881146c38675ce128b8ea702020c951564c9edc",
        "snapshot_id": "bc9ba9b3-bd76-4cd2-88a4-d5423850f383",
        "manifest_sha256": "b2b08e7d3baf049d02a86822f25e41f4b22e140dc2833c219bb00d74d89737f1",
        "product_count": 38,
    },
    "hz46_hasb_4": {
        "store": "5659",
        "group": "regionale-hz",
        "publication_sha256": "68184db39b6cb9878d6eab2e804ab767310390135e5f12772762329c661ac087",
        "receipt_sha256": "20960935b4ff65a1754e24a642699bd84e03194b72975a2871a6adfaa647cd0c",
        "snapshot_id": "962b80c9-a0bc-4553-8aa8-adf15857573b",
        "manifest_sha256": "c17eb05f4378f77c469175d94448b319895370ee2b51e13871fa4800e636e687",
        "product_count": 13,
    },
}
_SHA = re.compile(r"[0-9a-f]{64}")


def _read_verified(path: Path, root: Path, limit: int, digest: str | None = None) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or symlinked immutable publisher evidence")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or resolved.suffix != ".json":
        raise ValueError("Publisher evidence outside approved storage")
    with resolved.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit or (digest is not None and sha256(data).hexdigest() != digest):
        raise ValueError("Publisher evidence size/hash mismatch")
    return data


def _strings(value: object) -> set[str]:
    if type(value) is str:
        return {value}
    if isinstance(value, list):
        return set().union(*(_strings(item) for item in value))
    if isinstance(value, dict):
        return set().union(*(_strings(item) for item in value.values()))
    return set()


def publisher_only_hotspots(
    root: Path, *, store_id: str, snapshot_id: str, manifest_sha256: str,
    record: dict, day: date, valid_from: date, valid_until: date,
) -> dict[int, list[dict]]:
    """No network or DB access; all visible detail text is a verified original.

    Returns {} on missing/unsupported evidence rather than an unverified link.
    Caller must already have verified the selected-store manifest and viewer.
    """
    slug = record.get("slug")
    trust = _TRUSTED_PUBLICATIONS.get(slug) if type(slug) is str else None
    if (trust is None or type(store_id) is not str or store_id != trust["store"]
            or snapshot_id != trust["snapshot_id"]
            or manifest_sha256 != trust["manifest_sha256"]
            or record.get("publication_sha256") != trust["publication_sha256"]
            or type(day) is not date or type(valid_from) is not date
            or type(valid_until) is not date or not valid_from <= day <= valid_until):
        return {}
    root = root.resolve(strict=True)
    evidence_root = root / "netto-html"
    location = evidence_root / (
        "publitas-product-details-" + slug + "-" + trust["publication_sha256"]
    )
    if location.is_symlink() or not location.is_dir() or not location.resolve(strict=True).is_relative_to(evidence_root):
        return {}
    try:
        source = _read_verified(
            Path(record["publication_path"]), evidence_root, 2 * 1024 * 1024,
            trust["publication_sha256"],
        )
        projected = scan_netto_review_candidates(
            source, trust["publication_sha256"], store_id=store_id,
            day=day, valid_from=valid_from, valid_until=valid_until,
        )
        receipt_bytes = _read_verified(
            location / "receipt.json", location, 256 * 1024,
            trust["receipt_sha256"],
        )
        receipt = json.loads(receipt_bytes)
        receipt_strings = _strings(receipt)
        if not {trust["publication_sha256"], trust["snapshot_id"],
                trust["manifest_sha256"], slug, trust["group"]}.issubset(receipt_strings):
            raise ValueError("Capture receipt provenance mismatch")
        files = sorted(location.iterdir())
        if (len(files) != trust["product_count"] + 1
                or {path.name for path in files if path.name == "receipt.json"} != {"receipt.json"}):
            raise ValueError("Incomplete or unexpected retained publisher products")
        details: dict[int, dict] = {}
        for path in files:
            if path.name == "receipt.json":
                continue
            raw = _read_verified(path, location, 2 * 1024 * 1024)
            digest = sha256(raw).hexdigest()
            if digest not in receipt_strings or digest[:12] not in path.name:
                raise ValueError("Product hash not in independently verified receipt")
            product = json.loads(raw)
            pid, hid = product.get("id"), product.get("hotspotId")
            title = product.get("title")
            if (type(pid) is not int or pid <= 0 or pid in details
                    or type(hid) is not int or hid <= 0
                    or type(title) is not str or not 1 <= len(title.strip()) <= 250):
                raise ValueError("Invalid publisher product detail identity")
            description = product.get("description")
            if description is not None and (type(description) is not str or len(description) > 3000):
                raise ValueError("Unbounded publisher product description")
            details[pid] = {"hotspot_id": hid, "title": title.strip(),
                            "description": description or ""}
        ids = {pid for candidate in projected["candidates"]
               for pid in candidate["publisher_product_ids"]}
        if len(details) != trust["product_count"] or ids != set(details):
            raise ValueError("Publisher details and publication IDs mismatch")
        pages: dict[int, list[dict]] = {}
        for candidate in projected["candidates"]:
            page, rect = candidate["page_number"], candidate["rectangle"]
            if page is None or rect is None:
                continue  # no page-size evidence: never render a guessed box
            products = [details[pid] for pid in candidate["publisher_product_ids"]]
            if any(item["hotspot_id"] != candidate["hotspot_id"] for item in products):
                raise ValueError("Publisher detail belongs to a different hotspot")
            title = " · ".join(item["title"] for item in products)
            description = "\n".join(item["description"] for item in products
                                    if item["description"])
            pages.setdefault(page, []).append({
                "rectangle": rect, "title": title[:1200],
                "description": description[:3000],
                "hotspot_id": candidate["hotspot_id"],
                "source": "publitas_publisher_only",
            })
        return pages
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError):
        return {}
