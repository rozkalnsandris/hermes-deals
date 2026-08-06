# ALDI A3.0 authoritative rollover reconciliation

Issue: #191  
Upstream: #80, #121, #165

This gate reconciles one exact `REVIEW_REQUIRED` ALDI A3.0 acquisition without weakening the strict positional `41/41` automatic-promotion rule.

## Bound artifact

- workflow run: `31105044968`;
- artifact ID: `8969175974`;
- artifact ZIP SHA256: `fce7766060b9ff32874b55e474ea28a957b9ee21a7b0e2ecbe11952c36879bd4`;
- registered commit: `10e22b745a92bcf4e7213aafe83e165e08719c99`;
- dispatcher manifest SHA256: `2c6e8f90f30a55be9b02e7f67b4af668a0d29b60542de7174cb6ece484c6491b`;
- authoritative report SHA256: `ece18d2c357236d77ae4ed453cf8bdc9cd642aec675abe1463dcddf3b15d3925`;
- manual-review JSON SHA256: `f6b4a4e32f7c038a0ef18402bc5ef7680494abe419b7bc7738f0ae74d4daeca3`.

The immutable receipt is:

```text
config/aldi-a30-rollover-reconciliation-receipt-31105044968.json
```

The validator accepts only the exact receipt bytes and exact artifact digest.

## Reconciled result

- current pages: `41`;
- preview pages: `41`;
- positional visual matches: `36`;
- exact content-set matches: `39`;
- moved byte-identical pages: `3->4`, `4->5`, `5->37`;
- old-only pages: `37,41`;
- new-only pages: `3,41`;
- duplicate content groups: none.

Manual classification is fixed:

- new current page `3` is an offer page and enters the new current shadow ledger;
- old preview page `37` is a removed non-offer competition page and is not carried forward;
- old/new page `41` is a changed non-offer information page and remains excluded from automatic offer extraction.

Any changed page mapping, classification, count, SHA256, byte size, report state or safety flag fails closed.

## Verification

After extracting the exact GitHub artifact so that `dispatcher-evidence-manifest.json` is directly under `<EVIDENCE_ROOT>`, run:

```bash
python tools/aldi_a30_rollover_reconciliation.py \
  --receipt config/aldi-a30-rollover-reconciliation-receipt-31105044968.json \
  --evidence-root <EVIDENCE_ROOT> \
  --artifact-sha256 fce7766060b9ff32874b55e474ea28a957b9ee21a7b0e2ecbe11952c36879bd4 \
  --output <OUTPUT_JSON>
```

A successful result is limited to:

```text
shadow_reconciliation_accepted
next_step_scope=shadow_parser_and_parity_only
```

## Safety boundary

This gate does not:

- promote the source automatically;
- change the strict `41/41` rule;
- approve or publish offers;
- write PostgreSQL or Review state;
- deploy or restart production;
- install or enable a scheduler;
- execute B15M2 V08.

A later parser/parity shadow run and every production action remain separately authorized.
