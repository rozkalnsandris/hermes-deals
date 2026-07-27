from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceConfig:
    chain: str
    enabled: bool
    priority: int
    url: str
    scope: str
    notes: str
    keywords: tuple[str, ...]
    store_external_id: str | None = None
    store_internal_id: str | None = None
    store_name: str | None = None


def load_sources(path: Path) -> list[SourceConfig]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError("Unsupported sources.json schema_version")

    result: list[SourceConfig] = []
    for item in raw["sources"]:
        result.append(
            SourceConfig(
                chain=item["chain"],
                enabled=bool(item.get("enabled", True)),
                priority=int(item.get("priority", 99)),
                url=item["url"],
                scope=item.get("scope", "unknown"),
                notes=item.get("notes", ""),
                keywords=tuple(item.get("keywords", [])),
                store_external_id=item.get("store_external_id"),
                store_internal_id=item.get("store_internal_id"),
                store_name=item.get("store_name"),
            )
        )
    return result
