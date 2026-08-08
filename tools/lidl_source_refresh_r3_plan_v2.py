#!/usr/bin/env python3
from __future__ import annotations

from hashlib import sha256
import json

import lidl_source_refresh_r3_plan as v1


COMPAT_VERSION = "lidl-source-refresh-r3-plan-v2-r2-manifest-digest"


def _r2_manifest_digest(payload: object) -> str:
    """Match R2 manifest_digest(): compact sorted JSON, no trailing newline."""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def install_r2_digest_contract() -> None:
    # R3 v1 used its presentation JSON bytes (which include a trailing newline)
    # for semantic digests. R2's authoritative manifest_digest() does not.
    # Keep file output formatting unchanged while aligning only semantic hashes.
    v1._digest_payload = _r2_manifest_digest


def main() -> int:
    install_r2_digest_contract()
    return v1.main()


if __name__ == "__main__":
    raise SystemExit(main())
