# #1183 — EDEKA Monday shadow monitor policy (source-only)

Owner decision (2026-11-15):
`APPROVE hermes-deals #1183 EDEKA-POLICY=MONDAY-AFTER-VALID_FROM SOURCE-ONLY NO-LIVE`.

## Reason and bounded behavior

The actual 2026-11-15 Sunday source contained the verified EDEKA Patzer market
header and footer for **2026-11-16 through 2026-11-21**. The original
Sunday-scheduled EDEKA shadow monitor was pinned to an older audit checkout;
three scheduled attempts failed with `zero distinct valid_from`. Merged
PR #945 handles the newer `Gültig vom ... bis zum ...` grammar, but its
strict parser correctly refuses to accept a Monday-starting campaign on Sunday.

The owner-approved **shadow-monitor-only** schedule is:

```ini
OnCalendar=Mon *-*-* 00:10:00 Europe/Berlin
```

The new source candidate is
[`config/hermes-edeka-weekly-monitor-monday.timer.example`](../config/hermes-edeka-weekly-monitor-monday.timer.example).
It preserves the previously installed timer's 00:10 local clock time,
`Persistent=true`, `AccuracySec=5min`, target service, failure handler,
and all non-calendar bytes. No regular production collector, Lidl timer,
parser, cache, provenance, publication, or retry policy changes are approved.

| Identity | SHA-256 |
| --- | --- |
| Dated installed Sunday timer, 2026-11-15 | `6bc3cddbd77a925546032ae0a22abc75631d5f9ef36d01d98731a1bcb54fc31d` |
| Reviewed Monday candidate | `214a54a9c652dd38169987ba0672ec5853cc8f17f59734a318f7044ffa0d8178` |

The candidate is not activated by adding it to GitHub.

## Source acceptance

`backend/tests/test_edeka_monday_shadow_schedule.py` verifies:
- **exact** one-line Sunday-to-Monday timer delta and candidate digest;
- deterministic output from the existing non-activating EDEKA activation
  planner with no implicit LIVE/production/Review/publication authority;
- market-bound `2026-11-16..2026-11-21` weekly validity parses on Monday,
  but is rejected on Sunday `2026-11-15`, after expiry and too early;
- incorrect market/link, incomplete header and conflicting footer fail
  closed; immutable snapshot and market identities are preserved.

Existing #945 regressions continue to cover ambiguous/missing dates, legacy
start compatibility, extra unrelated ranges and freshness bounds. Keep strict
`backend/app/parsers/edeka.py` unchanged.

## Future cutover — separately owner-gated

1. Before any mutation, revalidate **current GitHub merged source SHA**,
   actual RPi5 installed timer/service/alert bytes and metadata, existing
   audit checkout HEAD, exact registration/control fingerprints, conflicting
   locks and timers, and `/run/reboot-required` state. Dated evidence above
   is not a valid future preflight.
2. Prepare and review an **exact forward migration** for the pinned EDEKA
   checkout, registration/control identities, Monday unit and systemd.
   The historical `tools/runner/reschedule_edeka_weekly_monitor.py` is a
   **one-shot Monday-to-Sunday migration** with stale SHA/fingerprint pins;
   do not reuse or edit those historical bindings as a shortcut.
3. Recognize `Persistent=true`: when an overdue Monday timer is enabled/
   restarted, systemd may immediately trigger a catch-up run. The LIVE
   plan must explicitly decide its catch-up behavior and preserve
   scheduled collector/retained-evidence/DB gates; there is **no standing
   authority** to perform such an execution.
4. Owner separately authorizes the exact reviewed LIVE sequence, including
   any source checkout update, unit/registration changes and expected
   runtime effects. On mutation error/drift, capture read-only evidence
   and **STOP without automatic retry or rollback**.
5. Verify the next genuine scheduled result, its campaign and source
   provenance, shadow evidence, application notification disposition,
   production-write exclusions and current timer state. A CI PASS or
   timer `active` alone does not prove recovery.

No LIVE state was changed by this source candidate. Merge of this PR
is not systemd, deployment, runtime, rollback or publication authorization.
