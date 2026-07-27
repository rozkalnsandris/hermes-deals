# Runtime compatibility review

The current backend stack is deliberately small and ARM64-safe for the Raspberry Pi 5.

| Component | Deployed reviewed pin | Role |
|---|---:|---|
| Python | 3.13.14-slim-bookworm | FastAPI + collector runtime |
| FastAPI | 0.139.2 | REST/OpenAPI API |
| Uvicorn | 0.51.0 | ASGI server |
| Pydantic | 2.13.4 | input/output contracts |
| SQLAlchemy | 2.0.51 | ORM/database access |
| Psycopg | 3.3.4 | PostgreSQL driver |
| Alembic | 1.18.5 | schema migrations |
| PostgreSQL | 18.4-bookworm | source of truth |
| Nginx | 1.30.4-alpine | reverse proxy + temporary diagnostics UI |

## Decisions checked in the 2026-07-24 code review

- SQLAlchemy 2.x transaction semantics support the explicit commit/rollback style used by the project. The controlled Lidl write intentionally verifies the committed first pass with a second exact-set read/write attempt.
- PostgreSQL `ON CONFLICT` is backed by the deployed `uq_offer_candidates_snapshot_offer` unique constraint on `(snapshot_id, source_offer_id)`. Real PostgreSQL concurrency, rollback atomicity and idempotent replay have been validated.
- Pydantic remains the parser-to-core contract boundary. Cross-field validity now rejects `valid_until < valid_from`.
- PostgreSQL 18 uses the versioned `PGDATA` layout; the named volume remains mounted at `/var/lib/postgresql`.
- Nginx preserves `/api/...` paths and is prepared for `/ws/...` Upgrade headers.
- Playwright remains a fallback collector technology and is not installed in the core runtime.

`backend/requirements.txt` contains the direct pins. Deploy verification runs `pip check` and records the resolved environment in `runtime-requirements.lock` on the RPi5.
