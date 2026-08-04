# Netto N25 title and package review policy v1

## Decision

Card geometry and normal-price extraction passed the genuinely blind Dresden
N24 evaluation, but card/price success does not make an offer publishable.

Until a later independent test reaches the required thresholds:

- no title is selected automatically;
- no package is selected automatically;
- title and package candidates may be stored as evidence;
- every extracted card requires review before approval or publish;
- no automatic approval or publish action is allowed.

## Evidence

N24 evaluated 61 true predicted cards:

- combined full title-token coverage: `46/61 = 75.41%`;
- required title threshold: `90%`;
- combined partial/full evidence: `56/61 = 91.80%`;
- automatic package selections: `0`;
- required package threshold: `90%`.

Partial evidence is useful to reviewers but is not sufficient for an automatic
canonical title.

## Truth-pack identity repair

The previous reader truth-pack source generated every corpus key with the
literal segment `store5659`, even when `--store-id 8681` was selected.

N25 makes the corpus key store-aware:

`<validity>-store<selected store ID>-<publication>-<source SHA prefix>`

Examples:

- Dortmund: `...-store5659-...`
- Dresden: `...-store8681-...`

Historical captures remain immutable. Only future captures use the repaired
key.

## Production status

Production integration remains blocked. After N25 passes, the next gate is a
new weekly canary for the family store `5659`, with title/package kept in
Review.
