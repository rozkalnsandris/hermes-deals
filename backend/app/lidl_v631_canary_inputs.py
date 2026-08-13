from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from app.lidl_v631_c3_readonly_preflight import LidlC3ReadonlyPreflightError

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def load_reviewed_canary_receipt(
    path: Path,
    *,
    expected_sha256: str,
) -> tuple[bytes, dict[str, Any], str]:
    """Load one exact reviewed Lidl canary receipt without product-specific constants."""
    if not SHA256_RE.fullmatch(expected_sha256):
        raise LidlC3ReadonlyPreflightError("reviewed receipt SHA-256 is invalid")
    if not path.is_file() or path.is_symlink():
        raise LidlC3ReadonlyPreflightError("reviewed receipt is missing or unsafe")

    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise LidlC3ReadonlyPreflightError("reviewed receipt SHA-256 mismatch")
    try:
        receipt = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LidlC3ReadonlyPreflightError("reviewed receipt is invalid JSON") from exc
    if not isinstance(receipt, dict):
        raise LidlC3ReadonlyPreflightError("reviewed receipt root must be an object")
    if receipt.get("kind") != "lidl_one_row_canary_review_receipt":
        raise LidlC3ReadonlyPreflightError("reviewed receipt kind mismatch")

    family = str(receipt.get("family") or "").strip()
    selected = receipt.get("selected")
    if not family or not isinstance(selected, dict):
        raise LidlC3ReadonlyPreflightError("reviewed receipt family/selected row is missing")
    row_binding = str(selected.get("row_binding_sha256") or "")
    if not SHA256_RE.fullmatch(row_binding):
        raise LidlC3ReadonlyPreflightError("reviewed row binding SHA-256 is invalid")

    return raw, receipt, row_binding
