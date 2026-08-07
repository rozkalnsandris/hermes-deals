# ALDI Gate D RPi5 exact-evidence discovery

Issue: #223  
Parent automation issue: #165  
Gate D builder merge: `ca23e7c9ed197bcf61294e841e7f370b26cbc770`

## Purpose

Gate D can build the offline visual adjudication pack only from exact retained frozen evidence. The RPi5 has accumulated multiple audit and shadow run directories, so the next execution step must not guess which local paths are authoritative.

This discovery gate is read-only. It identifies exact retained inputs and produces a deterministic plan. It does not create the Gate D review pack and does not authorize manual adjudication, parser execution, candidate creation or any production action.

## Required identities

The planner requires:

- A2.1 archive SHA256 `fa16df4db701e90f38bea0387a278750415ba03628f1fe1cc34ffb2833f2985d`;
- A2.1 adjudicated projection SHA256 `64699b7ede52dcaa5b85f3306426f3b90399dd037209621a38bacd166161d5ea`;
- Gate B plan SHA256 `3188821faa36a6d9fb598fde521a59993e6cb11678a8160e4afead4ba4fcfdd4`;
- current page 3 SHA256 `ad297cdd2f3dc728f0114fcb8a06c6d2c6131f4b342173b134d9e99bd092ae7c`;
- one unambiguous valid legacy A3.0 page-set identity containing exactly 49 current and 41 preview pages.

## Discovery scope

The planner scans only the explicitly supplied ALDI shadow state root.

It looks for:

- `hermes-deals-aldi-a21-*.tar.gz` files matching the exact frozen archive SHA;
- retained `a21-adjudicated-projection.jsonl` files matching the exact projection SHA;
- A3.0 `a30-v02-runs/*/reports/page-image-manifest.json` candidates;
- the corresponding `raw/page-images/current` and `raw/page-images/preview` files;
- authoritative-cycle `evidence/pages/current/page-003.img` copies matching the exact current page-3 SHA.

Every accepted path must resolve inside the supplied state root. Symlinked evidence is not accepted.

The legacy page manifest and all 90 image files are validated through the already merged Gate D validator. Valid runs are grouped by canonical page-set SHA256. Multiple retained copies of the same exact page set are allowed and reported. More than one distinct valid page-set identity is blocked as ambiguous instead of selecting one by timestamp.

## Decisions

### `READY_FOR_GATE_D_EXECUTION`

Returned only when all required evidence classes exist and every valid legacy A3.0 run belongs to one canonical page-set identity.

This status still does **not** execute Gate D. The output explicitly keeps:

```text
review_pack_execution_authorized=false
production_eligible=false
```

The next step is a separately owner-authorized RPi5 execution workflow/dispatcher that consumes this exact discovery plan and invokes the merged Gate D review-pack builder.

### `WAIT_FOR_EXACT_EVIDENCE`

Returned when one or more required exact evidence classes are missing. `missing_inputs` names each missing class. Missing evidence must never be interpreted as zero offers or successful parity.

### `BLOCKED_AMBIGUOUS_LEGACY_EVIDENCE`

Returned when more than one distinct, internally valid 90-page legacy A3.0 page-set identity exists under the allowed state root. A human-controlled follow-up must resolve which frozen family is authoritative before execution.

## Output contract

The JSON plan contains:

- root-relative selected paths only;
- every exact archive, projection, legacy run and current-page-3 copy found;
- canonical legacy page-set identity;
- Gate B replay fingerprint and current manifest identity;
- deterministic discovery fingerprint;
- explicit missing or ambiguity reason;
- complete read-only safety contract.

Output is create-only. Repeating identical input against an identical existing file returns `unchanged`; differing existing bytes fail closed.

## Controlled invocation

After this implementation is merged, a read-only RPi5 invocation will use the exact merged repository Gate B plan:

```bash
python3 tools/aldi_gate_d_rpi5_evidence_discovery.py \
  --state-root /home/andris/.local/state/hermes-deals/aldi-perfect-shadow \
  --gate-b-plan config/aldi-weekly-gate-b-replay-plan-31105044968.json \
  --output /exact/create-only/path/aldi-gate-d-rpi5-evidence-plan.json
```

The eventual owner-authorized dispatcher will choose and protect the output path. This document does not authorize running that dispatcher or creating a review pack.

## Safety

The discovery gate performs no:

- network acquisition;
- source or corpus mutation;
- parser execution;
- candidate creation;
- production database or Review write;
- automatic approval or publication;
- deployment or restart;
- scheduler, retry or systemd action;
- production canary;
- B15M2 V08 action.

The strict ALDI `41/41` automatic-promotion gate remains unchanged.
