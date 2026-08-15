# EDEKA weekly monitor owner-control boundary

This document reserves the source-only owner-control bridge that follows the merged non-activating unit-registration boundary in PR #672.

The final bridge will keep live root registration, systemd activation, source refetch, bounded retries, production writes and deploy behind separate explicit owner authorization. `activate` will require exact current-main registration plus explicit source-refetch and bounded-retry authority; `disable` and `rollback` will remain fail-safe control paths even after `main` advances.
