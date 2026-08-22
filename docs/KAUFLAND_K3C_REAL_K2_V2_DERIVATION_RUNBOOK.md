# Kaufland K3C REAL-K2 v2 read-only derivation runbook

Refs: #699, #701, #702, #747, #749, #750, #751, #752.

## Purpose

This runbook defines the reviewed repository-native procedure for deriving sanitized Kaufland K3 source-card v2 evidence from the already accepted immutable K2 packet.

Implementation:

`backend/app/kaufland_real_k2_v2_derivation.py`

The tool is **offline and read-only**. It does not collect live Kaufland data, does not run the K2 replay executor, does not write retained evidence, does not write DB/Review/publication state, and does not implement `backend/app/parsers/kaufland.py`.

The source-card contract remains `kaufland-k3-source-card-v2` from #749/#750.

## FAST-LANE v2.2 policy alignment

FAST-LANE v2.2 Composite is authoritative from #751.

Under v2.2:

- read-only preflight, evidence refresh, candidate verification and reconciliation are automation steps, not separate owner gates;
- merge remains an explicit owner gate;
- retained-evidence **mutation**, runtime/replay executor invocation, live collection with write effects, production DB/migration, deploy, scheduler/systemd/host/container, secrets and Cloudflare mutation remain Composite STRICT/live authority;
- a read-only K3C derivation does not itself authorize any later mutation;
- drift or ambiguity fails closed; no guessed role/family semantics are introduced to obtain PASS.

This file supersedes only the old procedural statement that a read-only REAL-K2 v2 evidence refresh itself requires a separate owner approval. It does **not** relax any provenance, immutability, parser, merge or live-mutation boundary in `docs/KAUFLAND_K3A_SOURCE_CARD_CONTRACT_RUNBOOK.md`.

## Accepted immutable K2 boundary

| Field | Accepted value |
| --- | --- |
| Store | `1503` / Kaufland Dortmund-Aplerbeck |
| Bundle key | `kaufland/1503/k2/2026-08-13_2026-09-02` |
| Bundle identity | `afdd992c547165259e760e05f41687793c56abc0af9869c8aa70f39d6f41dbbf` |
| Frozen K2 revision | `c451fb9027e87b62685557ad3c2c66701e912d57` |
| K2 parser-input contract | `kaufland-k2-v1` |
| Artifact count | `6` |
| Family count | `4` |
| Source role | `offer-overview` |
| Source path | `common/offer-overview.bin` |
| Source SHA-256 | `b95e735a707c9da023876ef280c6cbccfa1d7bf25d1638926eea035c27625e34` |
| Source bytes | `4440080` |
| Source content type | `text/html; charset=UTF-8` |

Accepted families remain the exact relation/source-identifier/identity tuples in `backend/app/kaufland_source_card_contract.py`. The K3C tool imports that mapping instead of maintaining a second family truth table.

## Reviewed invocation

Run from a reviewed checkout containing the K3C tool and current dependency lock. The retained root is explicit; there is no production-path default:

```bash
cd backend
python -m app.kaufland_real_k2_v2_derivation \
  --retained-root /home/andris/hermes-deals-retained-evidence
```

The command writes sanitized JSON to stdout only. It does not create an output file.

## Pre-semantic gates

Before semantic inspection, the tool:

1. requires BeautifulSoup `4.15.0` and explicitly selects parser backend `html.parser`;
2. computes a fingerprint only for the exact K2 target packet, not the whole retained root;
3. runs `verify_retained_bundle()` with the exact bundle key, frozen K2 revision, upstream contract and bundle identity;
4. requires verifier result `NO_OP`, `artifact_count=6`, `family_count=4`;
5. reloads the verified manifest and requires exactly one `offer-overview` record at `common/offer-overview.bin`;
6. requires the accepted SHA-256, byte count and content type;
7. reads only that exact overview artifact for semantic inspection;
8. decodes strict UTF-8;
9. keeps a process-local socket guard active so accidental network I/O fails as `NETWORK_FORBIDDEN`.

The verifier itself reads the exact packet to prove immutable identity. Semantic HTML inspection is limited to the accepted `offer-overview` artifact.

## Source-card ownership

Card discovery is conservative:

- candidate anchors must carry exactly one safe `kloffer-articleID` query value;
- `articleID` is evidence only and is **not** promoted to durable identity (#704 remains authoritative);
- the anchor must resolve to a bounded card-like ancestor;
- a candidate card must contain exactly one distinct `articleID` value;
- the receipt locator is a deterministic structural rawpath;
- `card_fragment_sha256` hashes the deterministic `html.parser` serialization of that exact card, while the accepted source artifact SHA binds the underlying immutable retained bytes.

Cards that do not satisfy these conditions are not silently promoted.

## Explicit price-role evidence

The tool never assigns roles by numeric ordering.

### Public promo

A promo candidate requires the explicit German marker `nur` within a bounded card-local scope containing exactly one defensible price amount. XTRA and old/reference scopes do not satisfy promo.

### Reference

Reference evidence requires exact structural marker class:

`k-price-tag__old-price`

An unlabelled larger number is never reference evidence.

### XTRA

XTRA evidence requires exact structural marker class:

`k-price-tag--xtra`

XTRA never satisfies public promo.

### Ambiguity

For each role:

- zero candidates => role remains absent;
- exactly one candidate => eligible for `PriceEvidence`;
- multiple candidates => that role fails closed with a stable `*_ROLE_AMBIGUOUS` blocker.

The v2 contract independently validates role ownership, locators, hashes, Decimal representation and cross-role separation.

## Family association

Family association is attempted only **after** a valid `SourceCardSemanticReceipt` exists.

`BOUND` requires an exact accepted K2 `source_identifier` occurrence within the same serialized card and the exact relation/source-identifier/family-identity tuple from the contract mapping.

If no accepted identifier is card-local, emit:

`UNBOUND / FAMILY_BINDING_MISSING`

If multiple accepted families appear card-local, emit:

`UNBOUND / FAMILY_BINDING_AMBIGUOUS`

No page-level date, publication window, nearby section, default family, closest-week or numeric inference may convert `UNBOUND` to `BOUND`.

`UNBOUND` carries no family relation, family identity, validity, current or preview semantics.

## Deliberate ambiguity probe

The derivation also runs one intentionally broad card-like selector. It is **not** used for semantic ownership. The probe must resolve to multiple nodes and is recorded as:

`AMBIGUOUS_CARD_OWNERSHIP`

If the real packet does not demonstrate that ambiguity control, the evidence gate remains BLOCKED.

## Determinism

The semantic projection is derived twice:

1. normal card/role construction order;
2. reversed card/role construction order.

Receipts are canonicalized by their contract identities. The full sanitized projections must be byte-equivalent as Python data structures; otherwise the run fails as `DERIVATION_NONDETERMINISTIC`.

## Target-scoped retained invariance

The fingerprint covers only:

`<retained-root>/kaufland/1503/k2/2026-08-13_2026-09-02`

For each exact target entry it binds path, type, mode, size, inode, `mtime_ns`, `ctime_ns`, and file-content SHA-256 (or symlink-target SHA where applicable). `atime` is intentionally excluded because a read may update access time.

After semantic derivation the tool:

1. reruns the exact K2 verifier;
2. recomputes the exact target-scoped fingerprint;
3. requires verifier decision equality;
4. requires `TARGET_FINGERPRINT_AFTER == TARGET_FINGERPRINT_BEFORE`.

Sibling or unrelated retained packets are never scanned by the fingerprint helper.

## Sanitized output contract

Output may contain only bounded structured data such as:

- accepted immutable identities;
- counts;
- stable reason codes;
- structural locators;
- SHA-256 evidence identities;
- canonical Decimal amounts from accepted semantic receipts;
- at most 12 semantic receipt samples;
- at most 12 family-association samples;
- target fingerprints;
- explicit all-false mutation/network flags.

It must not emit:

- full raw HTML;
- full card HTML;
- product titles/descriptions solely for diagnostics;
- cookies/session values;
- binaries;
- secrets;
- uncontrolled exception tracebacks or local path dumps.

## Evidence gate result

`PASS` requires all of the following in one deterministic projection:

- at least one semantic receipt;
- at least one explicit promo receipt;
- at least one explicit reference receipt;
- at least one explicit XTRA receipt;
- at least one card proving promo and XTRA as distinct roles;
- deliberate broad ambiguity probe -> `AMBIGUOUS_CARD_OWNERSHIP`;
- second derivation identical;
- post-verifier identical;
- retained target fingerprint unchanged.

Family association may legitimately remain `UNBOUND`; that does not erase independently proven card-local price semantics. However an UNBOUND card provides no validity/current/preview authority.

If any evidence is insufficient, the correct result is `BLOCKED`. Do not widen selectors or infer semantics merely to obtain PASS.

## #702 boundary

A K3C source merge does not start #702.

A later read-only K3C execution can establish reviewed real-K2 price-role evidence. #702 may consume only semantics actually proven by that evidence. Campaign validity/current/preview semantics additionally require reviewed `BOUND` family association evidence for the relevant card.

If the evidence remains insufficient, keep the affected parser semantics blocked or Review-only rather than guessing.

## Mutation classification

For this K3C source batch:

- Kaufland live network: **NO**
- retained evidence read: **NO**
- retained evidence write: **NO**
- K2 replay/runtime executor: **NO**
- #702 parser implementation: **NO**
- production DB write: **NO**
- Review/publication write: **NO**
- production deploy: **NO**
- scheduler/systemd/host/container mutation: **NO**
- secrets/Cloudflare mutation: **NO**

For a later K3C derivation execution, retained evidence **read** becomes YES, while all mutation/runtime/network flags above remain NO.
