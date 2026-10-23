# B15M2 V08 — source recovery (#20)

Verified 2026-10-23: the historical untracked V08 runner is absent from
GitHub main and the RPi5 checkout. Installed dispatcher and registrar exist,
but V08 was not registered. The host source was 36 commits behind GitHub.
The current migration head is 0008_household_state with 12 tables.

Source package: the named V08 Bash wrapper, tools/b15m2_v08_shadow.py,
tools/b15m2-v08-ci.Dockerfile and backend/tests/test_b15m2_v08_source_contract.py.

This is SOURCE-ONLY. Execution/registration/Docker/DB/host mutation, cleanup,
retained evidence and merge require distinct, exact owner authorizations.
The guarded engine refuses stale/dirty main and unregistered dispatch.
It archives only tracked exact source, builds source-bound images, starts a
networkless isolated PostgreSQL 18.4 database with no production mounts,
migrates to 0008, checks 12-table ownership and zero-row CRUD permissions,
rejects app DDL and broad schema/database permissions, verifies reader role,
runs complete backend pytest in a locked environment and a PostgreSQL
FastAPI health smoke, and emits a sanitized summary only after PASS.

## Exact registered engine provenance

The installed root-owned Bash wrapper is hash-checked by the dispatcher.
It reads Python engine bytes from the exact registered Git commit via
`git cat-file blob <registered-sha>:tools/b15m2_v08_shadow.py`.
It never executes the mutable host checkout Python file. The helper
retains its clean-main, origin, export-path and migration preflight.

This fixes only a source-code binding gap. **The V08 audit remains
NOT LIVE-ready:** current isolated PostgreSQL uses trust authentication,
so SCRAM positive/negative proof is incomplete; the API smoke covers
only /api/health rather than complete API/DB CRUD regression.
The owner must not treat a run as full #20 acceptance evidence.

Zero-row probes test privileges, not persisted CRUD behavior. Additional
gates remain for SCRAM authentication and full API/database CRUD regression,
production unchanged proofs, real runtime execution and GitHub artifacts.
Keep issue #20 OPEN until those proofs pass. No claims of host readiness
or runtime PASS are made by source CI.

On error no automatic retry, rollback or cleanup occurs: isolated resources
remain for a separately owner-authorized recovery. Never register or run
this harness under SOURCE-only authorization.
