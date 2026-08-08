#!/usr/bin/env python3
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Callable

import lidl_source_refresh_r3_plan as v1


COMPAT_VERSION = "lidl-source-refresh-r3-plan-v2-r2-manifest-digest"
_WRAPPER_MARKER = "_hermes_r3_r2_digest_scoped_wrapper"


def _r2_manifest_digest(payload: object) -> str:
    """Match R2 manifest_digest(): compact sorted JSON, no trailing newline."""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _call_with_r2_digest(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Use the R2 semantic digest for one call and always restore v1 state."""
    original_digest = v1._digest_payload
    v1._digest_payload = _r2_manifest_digest
    try:
        return fn(*args, **kwargs)
    finally:
        v1._digest_payload = original_digest


def install_r2_digest_contract() -> None:
    """Install an idempotent scoped build_plan compatibility wrapper.

    Do not mutate v1._digest_payload at import/module scope. R3 apply imports this
    module as a library, and a global monkeypatch would leak into unrelated tests
    and callers. The wrapper switches digest semantics only while build_plan runs.
    """
    current = v1.build_plan
    if getattr(current, _WRAPPER_MARKER, False):
        return

    def wrapped_build_plan(*args: Any, **kwargs: Any) -> Any:
        return _call_with_r2_digest(current, *args, **kwargs)

    setattr(wrapped_build_plan, _WRAPPER_MARKER, True)
    v1.build_plan = wrapped_build_plan


def main() -> int:
    install_r2_digest_contract()
    return v1.main()


if __name__ == "__main__":
    raise SystemExit(main())
