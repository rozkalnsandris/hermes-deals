# ALDI weekly Gate D visual review pack

Issue: #215  
Parent roadmap: #165  
Gate C merge: `4bea41069d74c10ef592dc36dd295210c1fc7fc2`

## Purpose

Gate C correctly returns `WAIT_FOR_VISUAL_LEDGER` because the exact A2.1
projection, completed legacy A3.1 parity bundle and current-page-3 Review-only
ledger have not yet been supplied together.

Gate D does not fabricate those missing decisions. It creates one immutable,
self-contained offline review pack so a human can inspect the exact frozen page
evidence and complete the two ledger templates in a separate controlled copy.

The output decision is:

```text
READY_FOR_MANUAL_VISUAL_ADJUDICATION
```

It is not a parity pass, parser result, Gate C ready result or production
authorization.

## Exact inputs

Gate D requires:

- the exact A2.1 adjudicated projection SHA256
  `64699b7ede52dcaa5b85f3306426f3b90399dd037209621a38bacd166161d5ea`;
- exactly 519 unique A2.1 rows with publication counts
  `346 auto_candidate`, `54 review_required`, `119 blocked_out_of_scope`;
- the frozen A3.0 90-page manifest and its exact local page-image root:
  `49 current + 41 preview`;
- the exact merged Gate B config already committed in the repository;
- the authoritative current page 3 image with SHA256
  `ad297cdd2f3dc728f0114fcb8a06c6d2c6131f4b342173b134d9e99bd092ae7c`;
- the reviewed commit SHA used to build the pack.

The existing Gate C loader validates the complete Gate B plan, including the
artifact identity, 41-page current manifest, 39/1/1 partition and safety
contract. A fingerprint-only object is not accepted.

## Output

Gate D creates a new output directory containing:

- `index.html` — offline page viewer with searchable candidate hints;
- all 90 byte-verified legacy page images;
- the exact current page 3 image;
- `legacy-card-ledger-template.json` — empty A3.1 card ledger template;
- `page3-fresh-shadow-extraction-template.json` — pending Review-only template;
- `candidate-hints.json` — the 400 A2.1 target hints;
- `review-index.json` — page/image identities and relative paths;
- `review-pack-manifest.json` — canonical input and output hash binding;
- `README.md` — reviewer instructions.

The templates intentionally contain:

- zero automatic card assignments;
- zero completed page-3 candidates;
- no production eligibility;
- no approval or publication decision;
- no claim that Gate C is ready.

Current page 41 is never introduced into fresh extraction.

## Controlled invocation

The legacy A3.0 run layout is expected to contain:

```text
reports/page-image-manifest.json
raw/page-images/current/page-001.img ... page-049.img
raw/page-images/preview/page-001.img ... page-041.img
```

The current authoritative artifact layout is expected to contain:

```text
pages/current/page-003.img
```

Example Python-only invocation:

```bash
python3 tools/aldi_weekly_gate_d_visual_review_pack.py \
  --projection /exact/a21-adjudicated-projection.jsonl \
  --legacy-page-manifest /exact/a30-run/reports/page-image-manifest.json \
  --legacy-page-root /exact/a30-run/raw/page-images \
  --gate-b-plan config/aldi-weekly-gate-b-replay-plan-31105044968.json \
  --current-pages-root /exact/authoritative-artifact/pages/current \
  --output /exact/create-only/aldi-gate-d-review-pack \
  --commit-sha <exact-reviewed-main-sha>
```

No shell wrapper or global strict shell mode is added.

## Failure policy

Gate D fails closed when:

- an input is absent or symlinked;
- the A2.1 SHA, row count, publication counts or offer identities drift;
- the frozen page sequence is incomplete or duplicated;
- any page byte count, SHA256 or image format differs from its manifest;
- Gate B is not the exact validated ready plan;
- current page 3 differs from its exact SHA or manifest identity;
- the output directory or temporary sibling already exists.

Validation happens before the final output directory is installed. Any partial
temporary output is removed after failure. Existing output is never overwritten.

## Manual completion boundary

The generated HTML and JSON templates are review aids. A later separately
scoped step must:

1. complete the legacy 90-page visual card ledger;
2. run the existing A3.1 bidirectional parity engine;
3. package the passing summary, 400 mapping rows, reverse coverage and empty
   blocker list as `ALDI_A31_COMPLETED_PARITY_BUNDLE_V01`;
4. complete current page 3 with stable `current:p003:cNNN` card IDs and
   Review-only reasons;
5. run Gate C again with the exact immutable outputs.

Gate D itself does none of those actions.

## Safety

Gate D performs no:

- network acquisition;
- parser execution;
- source or corpus mutation;
- candidate creation;
- production database or Review write;
- automatic approval or publication;
- deploy or restart;
- scheduler, retry or systemd action;
- production canary;
- B15M2 V08 action.

The strict `41/41` automatic-promotion gate remains unchanged and blocked.
