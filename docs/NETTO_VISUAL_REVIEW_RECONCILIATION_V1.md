# Netto visual review reconciliation V1

Issue: #95

This gate prepares a reproducible comparison between the already merged 100-cell first-pass shadow corpus and the independently produced N10 full visual-review ledger.

It does not import the N10 ledger, change the parser, approve offers, publish offers, write to the database or deploy anything.

## Bound evidence

- family-primary Netto store: `5659`;
- campaigns: `hz31_hasb_4` (26 cells) and `hz32_hasb` (74 cells);
- audited pages: 17;
- audited cells: 100;
- first-pass source archive SHA256: `882d61ad18ddca13680b97c0a27adf1a1db7874cabe337b61fc3ebc9b9d329f2`;
- N9 fixture manifest SHA256: `2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147`.

The first review may be supplied either as the raw first-pass JSON or as the existing lossless `gzip+base64` shadow fixture at:

```text
backend/tests/fixtures/netto/visual_cell_shadow_corpus_v1.json
```

The second review must use the N10 ledger schema with 100 `cell_reviews`, visual indexes `1..100`, the same fixture manifest, and all approval/publication safety flags disabled.

## Reconciliation contract

For every cell, the tool requires exact agreement on:

- cell ID;
- campaign;
- page number;
- first-review visual index `0..99` mapped to second-review index `1..100`.

It then compares:

- exact reviewed title;
- normalized title, so punctuation/case-only differences remain distinguishable from product differences;
- reviewed primary price using decimal comparison;
- first-pass and second-review verdicts.

Identity drift, missing cells, duplicate cells, wrong source hashes, unsafe flags or malformed prices are hard failures. Title and price differences are emitted as an explicit adjudication list.

## Safety contract

Every output keeps:

```text
promotion_ready=false
automatic_approval_enabled=false
automatic_publish_enabled=false
database_write_performed=false
deployment_performed=false
production_apply_authorized=false
```

Even a 100/100 consistent reconciliation does not promote the parser. Promotion requires a separate, explicitly reviewed change after the real N10 ledger is imported and the generated reconciliation report is audited.

## Intended run after ledger import

```bash
python tools/netto_visual_review_reconciliation.py \
  --first-review backend/tests/fixtures/netto/visual_cell_shadow_corpus_v1.json \
  --second-review backend/tests/fixtures/netto/n9_full_visual_review_v1.json \
  --output /tmp/netto-visual-review-reconciliation-v1.json
```

This PR only adds the fail-closed gate and regression tests. It does not close #95.
