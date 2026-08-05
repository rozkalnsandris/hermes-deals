# ALDI A3.0 frozen acquisition audit v1

## Purpose

This gate fixes the two concrete failures seen in the first ALDI A3.0 run:

1. the audit could accidentally receive a mutable `latest` A2.1 archive alias;
2. an expired ALDI magazine viewer returned HTTP 404 and aborted the run before
   the still-valid frozen iPaper page assets were acquired.

The gate remains shadow-only. It does not change the ALDI collector, database,
API, UI, timers, deployment, or production source tree.

## Frozen inputs

The runner binds the authoritative A2.1 archive:

- archive:
  `/home/andris/.local/state/hermes-deals/aldi-perfect-shadow/hermes-deals-aldi-a21-20260801T100533Z.tar.gz`
- archive SHA256:
  `fa16df4db701e90f38bea0387a278750415ba03628f1fe1cc34ffb2833f2985d`
- adjudicated projection SHA256:
  `64699b7ede52dcaa5b85f3306426f3b90399dd037209621a38bacd166161d5ea`
- rows: `519`
- publication states:
  `346 auto_candidate`, `54 review_required`, `119 blocked_out_of_scope`

The source plan is derived only from the frozen `prospect-links.json` inside
that verified archive:

- current prospect: 49 pages, KW31;
- preview prospect: 41 pages, KW32;
- total: 90 official iPaper page images.

## Failure policy

Magazine and iPaper viewer landing pages are advisory discovery surfaces.
Their transport and HTTP results are recorded, but a 404 is not fatal.

Every frozen page image is required. A missing page, duplicate page,
unexpected page, unknown image response, or incomplete 49/41 sequence fails
the audit.

Official PDF candidates are optional capability evidence. When both PDFs have
matching page counts and at least 80% text-page coverage, the next gate may run
deterministic offer-to-page matching. Otherwise the next gate is image-assisted
text recovery. Neither outcome authorizes production writes.

## Run

After this branch is merged and the exact `main` commit is known:

```bash
sudo -u andris env \
  HERMES_AUDIT_EXPECTED_HEAD=<exact-main-sha> \
  /home/andris/hermes-deals/tools/run-hermes-deals-aldi-a30-acquisition-v02.sh
```

The runner writes evidence only under:

`/home/andris/.local/state/hermes-deals/aldi-perfect-shadow/a30-v02-runs/`

## Acceptance

The acquisition gate passes only when:

- the exact A2.1 archive and internal manifest verify;
- the exact A2.1 projection and 519-row summary verify;
- the frozen current/preview source plan is contiguous and week-bound;
- all 90 page images are present and plausible;
- viewer failures remain recorded as advisory;
- repository status remains clean;
- no database, deployment, collector, or production source action occurs.

This does **not** close issue #25 by itself. It removes the broken acquisition
precondition so the remaining A3.1 text recovery and bidirectional
offer-to-page verification can be completed from frozen evidence.
