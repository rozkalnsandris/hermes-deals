from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping
from urllib.parse import urlsplit


EXPECTED_REPOSITORY = "rozkalnsandris/hermes-deals"
EXPECTED_OWNER_LOGIN = "rozkalnsandris"
EXPECTED_OWNER_ID = 277435981
COMMAND_RE = re.compile(
    r"/hermes-lidl-source-inspect "
    r"target=(?P<target>current|next) "
    r"as_of=(?P<as_of>[0-9]{4}-[0-9]{2}-[0-9]{2})"
)


class LidlSourceInspectError(ValueError):
    pass


@dataclass(frozen=True)
class InspectCommand:
    target: str
    as_of: str


def canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def parse_comment(body: str) -> InspectCommand:
    if not isinstance(body, str):
        raise LidlSourceInspectError("comment body must be text")
    match = COMMAND_RE.fullmatch(body.strip())
    if match is None:
        raise LidlSourceInspectError(
            "comment does not match the allowlisted Lidl source inspect command"
        )
    as_of = match.group("as_of")
    try:
        parsed = date.fromisoformat(as_of)
    except ValueError as exc:
        raise LidlSourceInspectError("as_of is not a valid date") from exc
    if parsed.isoformat() != as_of:
        raise LidlSourceInspectError("as_of is not canonical YYYY-MM-DD")
    return InspectCommand(target=match.group("target"), as_of=as_of)


def authorize_event(event: Mapping[str, Any], *, repository: str) -> dict[str, str]:
    if repository != EXPECTED_REPOSITORY:
        raise LidlSourceInspectError("unexpected repository")
    sender = event.get("sender")
    if not isinstance(sender, Mapping):
        raise LidlSourceInspectError("event sender is missing")
    if sender.get("login") != EXPECTED_OWNER_LOGIN:
        raise LidlSourceInspectError("comment sender login is not allowlisted")
    if sender.get("id") != EXPECTED_OWNER_ID:
        raise LidlSourceInspectError("comment sender numeric ID is not allowlisted")

    issue = event.get("issue")
    if not isinstance(issue, Mapping):
        raise LidlSourceInspectError("issue payload is missing")
    if issue.get("pull_request") is not None:
        raise LidlSourceInspectError("source inspect commands are accepted only on issues")
    issue_number = issue.get("number")
    if isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number <= 0:
        raise LidlSourceInspectError("issue number is invalid")

    comment = event.get("comment")
    if not isinstance(comment, Mapping):
        raise LidlSourceInspectError("comment payload is missing")
    comment_id = comment.get("id")
    if isinstance(comment_id, bool) or not isinstance(comment_id, int) or comment_id <= 0:
        raise LidlSourceInspectError("comment ID is invalid")

    command = parse_comment(str(comment.get("body") or ""))
    return {
        "target": command.target,
        "as_of": command.as_of,
        "issue_number": str(issue_number),
        "comment_id": str(comment_id),
        "trigger_actor": EXPECTED_OWNER_LOGIN,
    }


def stable_source_identity(source_json: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(source_json)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LidlSourceInspectError("source JSON is invalid") from exc
    if not isinstance(payload, Mapping):
        raise LidlSourceInspectError("source JSON root must be an object")
    flyer = payload.get("flyer")
    if not isinstance(flyer, Mapping):
        raise LidlSourceInspectError("source JSON flyer object is missing")
    viewer_url = str(flyer.get("flyerUrlAbsolute") or "")
    document_url = str(flyer.get("hiResPdfUrl") or flyer.get("pdfUrl") or "")
    pages = flyer.get("pages") or []
    if not isinstance(pages, list):
        raise LidlSourceInspectError("source JSON pages must be a list")
    regions = sorted(
        str(row.get("code"))
        for row in (flyer.get("regions") or [])
        if isinstance(row, Mapping) and row.get("code") is not None
    )
    identity = {
        "official_flyer_id": str(flyer.get("id") or ""),
        "viewer_path": urlsplit(viewer_url).path,
        "document_path": urlsplit(document_url).path,
        "valid_from": str(flyer.get("offerStartDate") or ""),
        "valid_until": str(flyer.get("offerEndDate") or ""),
        "advertised_regions": regions,
        "page_count": len(pages),
    }
    for key in (
        "official_flyer_id",
        "viewer_path",
        "document_path",
        "valid_from",
        "valid_until",
    ):
        if not identity[key]:
            raise LidlSourceInspectError(f"stable identity field missing: {key}")
    return identity


def parser_input_identity(source_json: bytes) -> str:
    try:
        payload = json.loads(source_json)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LidlSourceInspectError("source JSON is invalid") from exc
    if not isinstance(payload, Mapping):
        raise LidlSourceInspectError("source JSON root must be an object")
    canonical = dict(payload)
    canonical.pop("dateTime", None)
    canonical.pop("warnings", None)
    return canonical_digest(canonical)


def product_link_count(source_json: bytes) -> int:
    payload = json.loads(source_json)
    flyer = payload.get("flyer") if isinstance(payload, Mapping) else None
    if not isinstance(flyer, Mapping):
        raise LidlSourceInspectError("source JSON flyer object is missing")
    count = 0
    for page in flyer.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        for link in page.get("links") or []:
            if not isinstance(link, Mapping):
                continue
            if (
                str(link.get("displayType") or "").casefold() == "product"
                or isinstance(link.get("productDetails"), Mapping)
            ):
                count += 1
    return count


def inspect_live_source(*, target: str, as_of: str) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    backend = root / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))

    import httpx
    from app.lidl_family_source_discovery import (
        FLYER_API_URL,
        HUB_URL,
        StoreBinding,
        discover_selected_store_flyers,
        selected_store_cookies,
    )

    today = date.fromisoformat(as_of)
    binding = StoreBinding()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "Chrome/150 Safari/537.36 HermesDeals-SourceInspect"
        ),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.4",
    }
    transport = httpx.HTTPTransport(retries=1)
    timeout = httpx.Timeout(90.0, connect=30.0)
    with httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers=headers,
        cookies=selected_store_cookies(binding),
        transport=transport,
        trust_env=False,
    ) as client:
        discovery, evidence = discover_selected_store_flyers(
            client,
            binding=binding,
            today=today,
            hub_url=HUB_URL,
            api_url=FLYER_API_URL,
        )

    selected = evidence.get(target)
    if selected is None:
        return {
            "schema_version": 1,
            "result": "WAIT_SOURCE",
            "reason": "selected_store_target_not_available",
            "target": target,
            "as_of": as_of,
            "store_external_id": binding.external_id,
            "source_content_exported": False,
            "rpi5_access": False,
            "corpus_write": False,
            "database_write": False,
            "review_write": False,
            "production_deploy": False,
            "systemd_change": False,
        }

    stable = stable_source_identity(selected.source_json)
    summary = {
        "schema_version": 1,
        "result": "SOURCE_AVAILABLE",
        "reason": "sanitized_selected_store_source_identity",
        "target": target,
        "as_of": as_of,
        "store_external_id": binding.external_id,
        "store_entity_id": binding.entity_id,
        "flyer_identifier": selected.flyer_identifier,
        "route_region": selected.route_region,
        "valid_from": selected.valid_from,
        "valid_until": selected.valid_until,
        "official_flyer_id": selected.official_flyer_id,
        "viewer_path": stable["viewer_path"],
        "document_path": stable["document_path"],
        "advertised_regions": stable["advertised_regions"],
        "page_count": selected.page_count,
        "product_link_count": product_link_count(selected.source_json),
        "pdf_sha256": selected.pdf_sha256,
        "raw_sha256": selected.raw_sha256,
        "stable_source_identity_sha256": canonical_digest(stable),
        "parser_input_identity_sha256": parser_input_identity(selected.source_json),
        "pdf_bytes": selected.pdf_bytes,
        "raw_bytes": selected.raw_bytes,
        "candidate_count": int(discovery.get("candidate_count") or 0),
        "source_content_exported": False,
        "rpi5_access": False,
        "corpus_write": False,
        "database_write": False,
        "review_write": False,
        "production_deploy": False,
        "systemd_change": False,
    }
    return summary


def write_outputs(path: Path, payload: Mapping[str, Any]) -> None:
    fields = {
        "result",
        "reason",
        "target",
        "as_of",
        "flyer_identifier",
        "route_region",
        "valid_from",
        "valid_until",
        "official_flyer_id",
        "page_count",
        "product_link_count",
        "pdf_sha256",
        "raw_sha256",
        "stable_source_identity_sha256",
        "parser_input_identity_sha256",
    }
    with path.open("a", encoding="utf-8") as handle:
        for key in sorted(fields):
            value = payload.get(key, "")
            if isinstance(value, (list, dict)):
                value = json.dumps(value, sort_keys=True, separators=(",", ":"))
            text = str(value)
            if "\n" in text or "\r" in text:
                raise LidlSourceInspectError(f"unsafe newline in output: {key}")
            handle.write(f"{key}={text}\n")


def main() -> int:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    auth = authorize_event(event, repository=os.environ["GITHUB_REPOSITORY"])
    auth_output = os.environ.get("AUTH_OUTPUT")
    if auth_output:
        with Path(auth_output).open("a", encoding="utf-8") as handle:
            for key in sorted(auth):
                handle.write(f"{key}={auth[key]}\n")

    summary = inspect_live_source(target=auth["target"], as_of=auth["as_of"])
    summary_path = Path(os.environ["SUMMARY_PATH"])
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_outputs(Path(os.environ["GITHUB_OUTPUT"]), summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
