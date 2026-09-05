from __future__ import annotations

import os


# Runtime-only provenance marker for the guarded issue #19 API/UI release.
# It carries no publication or data-write authority; the focused regression
# suite binds the requested-date and Review-only contracts before release.
_NETTO_ISSUE19_RELEASE_CONTRACT = "requested-date-window+review-only-v1"


# API/runtime processes always provide DATABASE_URL. Standalone package CLIs
# such as `python -m app.<tool> --help` must remain importable without it.
if "DATABASE_URL" in os.environ:
    from app import netto_daily_special_runtime_patch as _netto_daily_special_runtime_patch
    from app import weekly_special_runtime_patch as _weekly_special_runtime_patch
    from app import current_deals_route_installer as _current_deals_route_installer
    from app import canonical_catalog_route_installer as _canonical_catalog_route_installer


__all__ = []
