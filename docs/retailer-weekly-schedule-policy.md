# Hermes Deals weekly retailer collection schedule

Hermes Deals uses one default weekly collection window for the four family retailers:

- `Sun *-*-* 00:10:00 Europe/Berlin`

The publication reference is Sunday 00:00 Europe/Berlin. The ten-minute buffer avoids racing the normal midnight publication boundary while still collecting close to first availability.

## Retailer policy

| Retailer | Activation default | Current activation implication |
|---|---|---|
| Netto 5659 | Sunday 00:10 | Use this schedule when the still-gated unattended timer is eventually registered/activated. |
| Lidl physical-store | Sunday 00:10 | Existing registered Gate D timer is still live on Monday 06:15 until the separately authorized reschedule migration is applied. |
| ALDI Nord | Sunday 00:10 | Use this schedule when unattended weekly production activation is eventually approved. |
| EDEKA Patzer 071897 / 587881 | Sunday 00:10 | Source migration is merged; live timer remains on the prior Monday schedule until its separate live migration is authorized and applied. |

`config/retailer-weekly-schedule-policy-v1.json` is the machine-readable activation-default policy. It does not claim or mutate live scheduler state.

## Failure and retry semantics

Sunday 00:10 is a first-attempt time, not an assumption that every retailer must already be published. A retailer that is not yet available must remain an explicit `not_published_yet`/WAIT-style state and use its retailer-specific bounded retry policy. Missing, stale or failed evidence must never be converted into a genuine zero-offer result.

## Lidl registered transition

The existing Lidl Gate D registration is:

- registered commit: `907f45faf429f005f31e74aff16bb9ee5c4090a2`
- old schedule: `Mon *-*-* 06:15:00 Europe/Berlin`
- old plan fingerprint: `28277e25db006c82587b52bad02939d17ceb5eb455ec059e2cdc2ca5ff68ea31`
- old timer SHA256: `58e95d071813fec7f37d602cfdbd96f2f4d555db3f22d00b8d76d8066e53451e`

The prepared replacement is:

- new schedule: `Sun *-*-* 00:10:00 Europe/Berlin`
- new plan fingerprint: `651301e004e39360c7198721b32c299c58d1720c9409f06189e265ff311c4bb4`
- new timer SHA256: `beedb229d2203ab239f10de2772e086de58e4b7032e705897d064978aa840597`
- service and failure-alert unit hashes remain unchanged.

`tools/runner/reschedule_lidl_gate_d.py` preserves the old staged unit directory by archiving it under the old fingerprint, installs a new staged unit set at the registered path, changes only the timer schedule-derived bytes and plan trust record, reloads systemd, and restarts the already-enabled timer. It does not enable/disable the timer, write production data or deploy.

Because the timer is `Persistent=true`, the live migration requires separate owner authorization for the possible catch-up/source-fetch and existing bounded retry behavior.

## Authority

Merging schedule-policy or migration source does not change any live timer.

Each live scheduler mutation remains separately owner-authorized and must be verified against the exact current GitHub source and the existing registered host state. Production DB, Review, publication and deployment authority are not implied by scheduler work.
