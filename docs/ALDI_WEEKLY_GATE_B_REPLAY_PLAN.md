# ALDI weekly automation Gate B replay plan

Issue: #200  
Parent roadmap: #165

## Purpose

Gate B turns the first reconciled real ALDI authoritative cycle into a deterministic, read-only shadow replay plan.

It does not run the parser or claim offer parity. It only proves which final-current pages are byte-identical carry-forward evidence, which page requires fresh shadow extraction, and which page is non-offer informational evidence.

## Exact evidence binding

The planner accepts only:

- workflow run `31105044968`;
- artifact ID `8969175974`;
- artifact ZIP SHA256 `fce7766060b9ff32874b55e474ea28a957b9ee21a7b0e2ecbe11952c36879bd4`;
- registered acquisition commit `10e22b745a92bcf4e7213aafe83e165e08719c99`;
- reconciliation receipt SHA256 `6e335a4c696ca3d43e5d1c4d0549a23b231db547ab9d5413b4a13b93de545ab9`;
- authoritative report SHA256 `ece18d2c357236d77ae4ed453cf8bdc9cd642aec675abe1463dcddf3b15d3925`;
- manual-review SHA256 `f6b4a4e32f7c038a0ef18402bc5ef7680494abe419b7bc7738f0ae74d4daeca3`.

The ZIP digest, receipt bytes, dispatcher manifest, reports and all 41 final-current page files are verified before a plan is produced. Symlinked, missing, malformed or hash-mismatched evidence fails closed.

## Reconciled page partitions

The exact final-current cycle contains 41 pages.

Gate B requires:

- 36 exact pages in the same position;
- three exact moved pages:
  - old preview `3` → new current `4`;
  - old preview `4` → new current `5`;
  - old preview `5` → new current `37`;
- new current page `3` → `fresh_shadow_extraction_required`;
- new current page `41` → `non_offer_informational_excluded`;
- old preview page `37` → removed competition page, never carried forward;
- old preview page `41` → superseded informational evidence, never carried forward.

The resulting partitions are exactly:

```text
carry_forward_parity=39
fresh_shadow_extraction=1
excluded_informational=1
```

No old page or new page may appear in more than one carry-forward mapping.

## Legacy A3.1 boundary

The existing A3.1 engine remains a frozen reference for its original corpus:

- 49 current pages;
- 41 preview pages;
- A2.1 projection SHA256 `64699b7ede52dcaa5b85f3306426f3b90399dd037209621a38bacd166161d5ea`;
- 346 automatic candidates;
- 54 Review-required candidates.

Gate B does not change those constants and does not pretend that the old 90-page corpus is the new weekly cycle.

Its identity is recorded with:

```text
reuse_mode=frozen_reference_only
```

A later controlled step may use the 39 proven carry-forward mappings as parity evidence and perform fresh shadow extraction for current page 3.

## Decisions

A complete new exact input produces:

```text
READY_FOR_SHADOW_REPLAY
```

A complete prior Gate B result with the same replay fingerprint produces:

```text
NO_OP
```

Malformed or incomplete prior evidence fails closed. A minimal fingerprint-only object is not accepted.

## Controlled execution

Use an extracted copy of the exact GitHub Actions artifact and the original ZIP file.

```bash
python3 tools/aldi_weekly_gate_b_replay_plan.py \
  --receipt config/aldi-a30-rollover-reconciliation-receipt-31105044968.json \
  --artifact-zip <exact-downloaded-artifact.zip> \
  --artifact-root <extracted-artifact>/audit-evidence \
  --output <new-output-directory>/aldi-gate-b-replay-plan.json
```

For a later exact-input no-op check, provide the previously completed plan:

```bash
python3 tools/aldi_weekly_gate_b_replay_plan.py \
  --receipt config/aldi-a30-rollover-reconciliation-receipt-31105044968.json \
  --artifact-zip <exact-downloaded-artifact.zip> \
  --artifact-root <extracted-artifact>/audit-evidence \
  --prior-plan <previous-plan.json> \
  --output <new-output-directory>/aldi-gate-b-replay-plan.json
```

The planner uses create-only output semantics. An existing byte-identical output is reported as unchanged; an existing different output is a hard failure.

## Safety contract

Every plan records:

```text
plan_only=true
network_acquisition_authorized=false
source_or_corpus_write_authorized=false
parser_execution_authorized=false
candidate_creation_authorized=false
production_database_write_authorized=false
review_write_authorized=false
automatic_approval_authorized=false
automatic_publication_authorized=false
production_deployment_authorized=false
scheduler_or_retry_authorized=false
production_canary_authorized=false
b15m2_v08_action_authorized=false
strict_41_of_41_gate_unchanged=true
```

`READY_FOR_SHADOW_REPLAY` authorizes only the next isolated shadow implementation step. It is not candidate parity, promotion approval, production eligibility, deploy approval or scheduler approval.
