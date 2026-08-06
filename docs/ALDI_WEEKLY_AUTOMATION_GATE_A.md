# ALDI Nord weekly automation — Gate A

Issue: #165

Gate A is a deterministic, read-only controller above the existing frozen A3.0 acquisition evidence and A3.1 offer-to-page parity ledger.

## Required identity

Every input must bind:

- retailer `aldi_nord`;
- scope `physical_store_flyer`;
- region `aldi_nord` with no ALDI Süd or other-region fallback;
- one explicit campaign ID and bounded validity window;
- an allowlisted official HTTPS ALDI Nord source URL;
- exact source and page-manifest SHA256 values;
- exact parser identity;
- exact parity-ledger identity and SHA256;
- candidate/review counts and zero unexplained cards;
- immutable evidence with `promotion_ready=false`.

## Decisions

- `READY`: a new fully verified source/parser/ledger identity may run through the existing shadow chain.
- `NO_OP`: the complete content-addressed identity exactly matches a prior validated Gate A result.
- `WAIT`: the source is not published, unavailable, or still Review-pending. This is never rendered as zero offers.
- `BLOCKED`: evidence mismatch, parser failure, unexplained cards, or invalid identity.

Changing the source, parser, ledger, campaign, page set, counts, or provenance changes the fingerprint and requires a new shadow run.

## Safety boundary

Gate A performs no network acquisition and authorizes no source/corpus mutation, database or Review write, automatic approval/publication, scheduler change, production canary, deploy, or B15M2 #20 action.

Two consecutive real weekly shadow families, replay/idempotency evidence, a canary plan, and later timer/monitor activation remain separate gates in #165.
