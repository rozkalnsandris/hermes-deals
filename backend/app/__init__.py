from __future__ import annotations

import os


# API/runtime processes always provide DATABASE_URL. Standalone package CLIs
# such as `python -m app.<tool> --help` must remain importable without it.
if "DATABASE_URL" in os.environ:
    from app import weekly_special_runtime_patch as _weekly_special_runtime_patch
    from app import current_deals_fast_route as _current_deals_fast_route


__all__ = []
