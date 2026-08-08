# Lidl source refresh R3 v2

R3 v2 is a read-only compatibility and workflow-hardening layer for issue #361.

## Why v2 exists

The retained R2 artifact was created by `tools/lidl_source_refresh_r2_scan.py`. Its `manifest_digest()` hashes compact, key-sorted UTF-8 JSON bytes without a trailing newline. The original R3 planner reused its presentation JSON serializer for semantic hashes; that serializer appends a trailing newline. The first live R3 planning run therefore failed closed with `artifact payload tree digest mismatch` before any corpus write.

`tools/lidl_source_refresh_r3_plan_v2.py` preserves the v1 plan/output behavior but installs the exact R2 semantic digest contract before invoking v1. Presentation JSON files may still end with a newline; semantic hashes do not include it.

## GitHub Actions hardening

The v2 issue-comment workflow is GitHub-hosted and owner-only. It uses exact full commit SHAs for the current stable GitHub-owned actions used by this workflow:

- `actions/checkout` v6.0.2: `de0fac2e4500dabe0009e67214ff5f5447ce83dd`
- `actions/upload-artifact` v7.0.1: `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`

The workflow retains least-privilege permissions, exact R2 artifact/run/head/repository binding, downloaded ZIP SHA-256 verification, exact owner login + numeric ID authorization, no self-hosted runner, no sudo, no corpus apply command, and no production write capability.

## Command

```text
/hermes-lidl-source-refresh-r3-plan-v2 artifact=9021545332
```

This command is planning only. A successful plan does not authorize corpus/source-review/scan/authority promotion, profile promotion, DB/Review writes, publication, deploy, systemd/timer changes, Gate C/D, or B15M2 V08.
