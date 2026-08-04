# Netto shadow gate corpus binding v1

## Purpose

This document hardens the promotion contract in
`NETTO_SHADOW_PROMOTION_AND_WEEKLY_CONTROLLER_V1.md`.

A corpus containing two campaign families is not sufficient by itself. **Every
field considered for promotion must independently contain audited evidence from
at least two frozen campaign families.** Evidence for package, for example,
cannot satisfy the campaign-diversity gate for title.

## Operational gate

`tools/netto_shadow_gate.py` wraps the base field metrics and enforces all of the
following before a field can remain promoted:

1. the corpus contains at least two campaign families;
2. the field itself contains at least two campaign families;
3. the field has at least the configured number of non-ambiguous samples;
4. precision reaches the field threshold;
5. coverage reaches the field threshold.

A failed condition routes only that field to `review_required`. It does not
change the result for unrelated fields.

Precision and coverage thresholds must be probabilities in the inclusive range
`0..1`. Invalid thresholds fail closed.

## Corpus identity

Every audit report records a deterministic, order-independent corpus identity:

- `corpus_sha256`;
- `corpus_row_count`;
- campaign IDs per field;
- parser identities;
- manifest SHA-256 values;
- PDF SHA-256 values.

Reordering the same frozen rows does not change the corpus identity. Changing a
value, classification, source binding, parser identity, page or card does.

## Imported N25/N26 policy binding

The focused hardening regression reads the already imported fixture:

`backend/tests/fixtures/netto/n25_title_package_review_policy_v1.json`

It confirms that the new gate retains the authoritative imported policy:

- title full coverage is `46/61 = 75.41%`, below the `90%` threshold;
- automatic package selections are `0/61`, below the `90%` threshold;
- production integration remains blocked;
- title and package therefore remain Review-only.

The synthetic and adversarial fixtures validate the gate mechanics. They do not
claim new production precision. A real promotion decision still requires an
immutable RPi5 corpus report generated from the imported N25/N26 truth-pack.

## Safety

This hardening does not enable approval, publication, deployment or database
writes. Missing field evidence is a blocking result, not a pass.
