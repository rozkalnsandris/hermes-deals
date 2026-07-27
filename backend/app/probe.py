from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.models import SourceSnapshot
from app.settings import get_settings
from app.source_config import SourceConfig

_JSON_LD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>', re.IGNORECASE)


def _strategy_hint(status: int | None, content_type: str | None, body: str, keyword_hits: dict[str, int]) -> str:
    ctype = (content_type or "").lower()
    if status in {401, 403, 429}:
        return "blocked_needs_browser_or_headers"
    if status is None:
        return "network_error"
    if 200 <= status < 300 and "json" in ctype:
        return "json_candidate"
    if 200 <= status < 300 and ("html" in ctype or "<!doctype html" in body[:500].lower()):
        if sum(keyword_hits.values()) >= 2:
            return "http_html_candidate"
        return "html_needs_inspection"
    if 300 <= status < 400:
        return "redirect_needs_inspection"
    return "manual_review"


def probe_source(db: Session, source: SourceConfig) -> SourceSnapshot:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    snapshot = SourceSnapshot(
        id=uuid.uuid4(),
        source_chain=source.chain,
        source_url=source.url,
        scope=source.scope,
        collected_at=now,
        content_bytes=0,
        keyword_hits={},
        json_ld_blocks=0,
        strategy_hint="pending",
        success=False,
    )

    try:
        headers = {
            "User-Agent": settings.http_user_agent,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
            "Cache-Control": "no-cache",
        }
        started = time.monotonic()
        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, connect=10.0), headers=headers) as client:
            response = client.get(source.url)
        elapsed_ms = round((time.monotonic() - started) * 1000)

        content = response.content
        text = response.text
        digest = hashlib.sha256(content).hexdigest()
        content_type = response.headers.get("content-type")
        keyword_hits = {kw: text.lower().count(kw.lower()) for kw in source.keywords}
        json_ld_blocks = len(_JSON_LD_RE.findall(text))

        folder = settings.raw_snapshot_dir / source.chain
        folder.mkdir(parents=True, exist_ok=True)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        suffix = ".json" if "json" in (content_type or "").lower() else ".html"
        path = folder / f"{stamp}-{digest[:12]}{suffix}"
        path.write_bytes(content)

        hint = _strategy_hint(response.status_code, content_type, text, keyword_hits)
        success = 200 <= response.status_code < 300 and len(content) >= 1000

        snapshot.final_url = str(response.url)
        snapshot.http_status = response.status_code
        snapshot.elapsed_ms = elapsed_ms
        snapshot.content_type = content_type
        snapshot.content_bytes = len(content)
        snapshot.sha256 = digest
        snapshot.snapshot_path = str(path)
        snapshot.keyword_hits = keyword_hits
        snapshot.json_ld_blocks = json_ld_blocks
        snapshot.strategy_hint = hint
        snapshot.success = success
    except Exception as exc:  # deliberately records a failed feasibility probe
        snapshot.strategy_hint = "network_error"
        snapshot.error = f"{type(exc).__name__}: {exc}"[:2000]

    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def snapshot_as_dict(snapshot: SourceSnapshot) -> dict[str, object]:
    return {
        "source": snapshot.source_chain,
        "success": snapshot.success,
        "status": snapshot.http_status,
        "bytes": snapshot.content_bytes,
        "elapsed_ms": snapshot.elapsed_ms,
        "strategy_hint": snapshot.strategy_hint,
        "keyword_hits": snapshot.keyword_hits,
        "json_ld_blocks": snapshot.json_ld_blocks,
        "final_url": snapshot.final_url,
        "error": snapshot.error,
    }
