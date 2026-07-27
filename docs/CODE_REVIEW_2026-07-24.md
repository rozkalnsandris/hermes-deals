# Hermes Deals full code/documentation review — 2026-07-24

## Scope reviewed

The review covered the complete current project tree, including:

- every Python module under `backend/app/`;
- all unit/regression tests under `backend/tests/`;
- Alembic migration/configuration;
- Dockerfiles and `docker-compose.yml`;
- Nginx config;
- source configuration and environment template;
- Makefile and verification scripts;
- temporary web diagnostics UI;
- README, architecture, compatibility, roadmap and all phase documents through Phase 2B19.

The Phase 2B19 failure log was checked against the actual v28 implementation and test suite.

## Critical finding fixed

`collector_cli.py` treated a legitimate integer zero as missing:

```python
int(report.get("rows_written_second_pass") or -1)
```

The persistence core's second pass was designed to return `0` on a correct idempotent replay. Because `0` is falsey, the CLI converted it to `-1` and raised a false failure. This was the direct cause of the v28 rollback.

The persistence core itself already had a passing test that asserted `rows_written_second_pass == 0`; the missing coverage was at the CLI/report boundary. v29 adds that boundary regression test.

## Additional correctness improvements included

1. **Exact first-write cardinality** — Phase 2B19 now requires exactly four mapped candidates rather than accepting any number >= 4.
2. **Canonical offer identity** — a missing, blank or whitespace-padded `source_offer_id` is rejected before persistence.
3. **Zero-distance OCR geometry** — `distance == 0` is no longer replaced by a fallback `9999` through Python truthiness.
4. **Offer validity window** — the Pydantic contract rejects `valid_until` earlier than `valid_from`.
5. **Stale documentation** — README, architecture, compatibility, roadmap, Phase2B19 and temporary UI are updated from the old Phase-1/Phase-2B4 state.
6. **Verification naming** — a generic `verify.sh` is introduced; `verify-phase1.sh` stays as a compatibility wrapper.

## Persistence design assessment

The controlled Lidl path is intentionally conservative and is suitable for the first single-worker write:

- real immutable `SourceSnapshot` SHA is checked immediately before persistence;
- only strict-ready, math-verified, dual-PSM rows are promoted;
- deterministic UUIDs are derived from immutable snapshot + retailer offer identity;
- unexpected existing rows abort; there is no delete-and-replace behavior on the Lidl path;
- persisted row payloads are compared exactly on replay;
- review/correction candidates are excluded.

## Deferred issue: concurrent idempotence

The current DB schema does not yet have a unique constraint such as an approved retailer identity key for `offer_candidates`, and `source_snapshots` also relies on application-level lookup for content SHA reuse. This is acceptable for the current single controlled worker but is not the final concurrent design.

The proper follow-up is a dedicated migration after auditing existing Netto/Lidl data, then PostgreSQL conflict-safe inserts. This is deliberately **not** included in the v29 recovery patch because schema changes and first-write recovery should not be combined.

## Legacy/general path note

`offer_store.save_offer_candidates()` (currently used by Netto) achieves retry behavior by deleting all rows for a snapshot and reinserting them. It is not used by the controlled Lidl path. It should be revisited when the common persistence layer is redesigned around DB-level uniqueness.

## Result expected from v29

A correct Phase 2B19 run should report:

- four approved candidates;
- four rows written on first pass;
- zero rows written on second pass;
- four Lidl rows after the write;
- unchanged SourceSnapshot count;
- recommendation `lidl_first_controlled_offer_write_valid`.

## Follow-up finding from the v29 deployment

The v29 application code passed all 99 live tests and the controlled persistence report proved the intended database behavior (`4` rows on the first pass, `0` on the second). A later deploy-only API verification step failed with `JSONDecodeError` because the shell command combined a pipe with `python3 -` and a here-document. Both mechanisms competed for the command's standard input; the here-document supplied the Python source and the API JSON was unavailable to `json.load(sys.stdin)`.

This was a deployment-verifier false-negative, not an application persistence failure. v30 removes the stdin collision by materializing the API response into a temporary file and validating that file explicitly. A deploy self-check now rejects the unsafe pipe/heredoc pattern.
