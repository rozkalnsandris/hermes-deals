# ALDI new-baseline weekly-shadow request producer

Issue: #682

This producer closes the missing ingress between a real, read-only ALDI acquisition and the already merged #687 weekly-shadow bridge.

## Two owner gates

1. `/hermes-aldi-new-baseline-weekly-shadow prepare`
   - exact owner/issue command only;
   - binds current `main`;
   - runs only on the dedicated RPi5 audit runner through a fixed root-owned dispatcher;
   - uses the existing isolated pinned Playwright 1.61.0 runtime;
   - fetches only `https://www.aldi-nord.de/angebote.html`;
   - writes no production DB, Review/publication, source corpus, schedule, or deployment state;
   - creates one immutable root-owned request and reports only its request SHA256 plus sanitized metadata.
2. `/hermes-aldi-new-baseline-weekly-shadow request=<sha256>`
   - existing #687 bridge validates Gate A → Gate B → Gate C → weekly evidence;
   - this is a separate owner authorization.

Installing or refreshing either dispatcher on RPi5 is a separate host/root authorization after merge.

## Weekly-family selection

ALDI can expose validity outliers that are not part of the active weekly family. The producer therefore does not use a global minimum/maximum validity range.

For every priced structured offer it derives a defensible validity start from the official payload. It then chooses exactly one ISO-week family:
- the modal validity-start ISO week wins;
- on Sunday, a tie prefers the family starting the next day;
- otherwise a tie prefers the closest weekly family;
- offers without any defensible validity start are never promoted into the selected family.

The Gate A campaign is normalized to the selected ISO week's Monday through Sunday, so a long-lived outlier cannot widen the weekly acceptance window.

## Exact visual identity, no fuzzy fallback

The producer reads ALDI's exact `objectID` values from the official `__NEXT_DATA__` payload. A selected structured offer is eligible only when its exact object ID binds to exactly one visible official DOM offer/product container.

There is no title, brand, price, OCR, or text-similarity fallback. Missing, duplicate, or ambiguous DOM identity blocks `prepare`.

Gate-B-safe candidate IDs are deterministic hashes of the original exact ALDI object ID. The structured payload hash and immutable raw source evidence allow that identity binding to be independently recomputed.

## Immutable evidence

A successful prepare retains locally on RPi5, root-owned and create-only under the request SHA:
- the exact official HTTP source response used for the structured offer map;
- the exact full-page rendered PNG used by the visual card ledger;
- `EVIDENCE.sha256`.

The request directory separately retains root-owned Gate A/B/C and execution-evidence JSON. Raw HTML or rendered images are not uploaded to GitHub Actions; the uploaded producer artifact contains only sanitized metadata and the evidence-manifest SHA256.

## Safety

The producer never uses:
- historical A3.0 `49 current + 41 preview` evidence;
- the legacy A3.1 projection or fuzzy matcher;
- the normal DB collector;
- Review/publication persistence;
- automatic retries or schedules.

A successful prepare does not authorize or perform:
- production DB writes;
- Review/publication writes;
- source/corpus mutation;
- production canary application;
- production deploy;
- historical #56 completion.

After a merge that changes `main`, both the producer registration and the existing #687 weekly-shadow bridge registration must be exact-SHA refreshed before their respective live owner-gated commands can run.
