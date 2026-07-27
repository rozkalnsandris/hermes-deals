# Phase 2B19 — first controlled Lidl offer persistence

Phase 2B19 performs the first intentional Lidl `offer_candidates` write.

It persists exactly four previously audited candidates that are simultaneously:

- `strict_ready`;
- `math_verified`;
- supported by both PSM 11 and 12;
- bound to the immutable canonical Lidl `SourceSnapshot`;
- unchanged by unit-price math;
- identified by a non-empty deterministic `source_offer_id`.

The write uses deterministic row UUIDs derived from the real snapshot UUID and `source_offer_id`, refuses to replace unexpected rows, and verifies a second persistence pass writes zero rows.

No OCR and no Lidl network fetch are performed in this phase.

## v28 false-negative and v29 correction

The v28 persistence core correctly produced numeric `rows_written_second_pass = 0`, but the CLI used:

```python
int(report.get("rows_written_second_pass") or -1)
```

Numeric zero is falsey in Python, so the expression became `-1` and the CLI incorrectly reported that idempotence had failed. The deploy rollback then safely removed only the attempted Phase-2B19 Lidl rows and restored Phase 2B18.

v29 fixes the report boundary to distinguish **missing** from a legitimate numeric zero and adds a regression test for this exact case.

The full review also tightened two adjacent correctness rules:

- the first controlled write must contain **exactly four**, not “at least four”, approved candidates;
- missing/blank `source_offer_id` is rejected before persistence.

An unrelated numeric-falsey geometry issue (`distance == 0`) in the OCR unit-price audit was also corrected and regression-tested.

## Deferred hardening

The current first-write path is intentionally single-worker and application-gated. DB-level uniqueness suitable for concurrent collectors and PostgreSQL `ON CONFLICT` handling belongs in a separate Alembic migration after this controlled write is proven. Mixing a schema migration into this recovery patch would increase risk without fixing the v28 failure.

## v29 post-write verifier false-negative and v30 correction

The v29 persistence path itself completed successfully: the first pass wrote exactly four rows and the second pass wrote zero rows. The subsequent deploy verifier failed before commit because its shell command attempted to use standard input twice at once:

```bash
printf '%s\n' "$LIDL_API" | python3 - "$EXPECTED_SNAPSHOT_ID" <<'PY'
```

`python3 -` reads the Python program from standard input, while the here-document also redirects that same standard input. The piped JSON therefore was not available to `json.load(sys.stdin)`, which saw EOF and raised `JSONDecodeError`. The rollback then correctly removed the four attempted rows and restored Phase 2B18.

v30 fixes only the deploy verification boundary: the Lidl API payload is written to a temporary JSON file, checked to be non-empty, and the Python verifier receives that file path as an argument. The application persistence code remains the reviewed v29 implementation. The deploy script also rejects any future same-line `pipe -> python3 - -> heredoc` pattern before making changes.
