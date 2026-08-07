# ALDI Gate D2 legacy family diagnostic

Issue: #261  
Upstream Gate D1 V2 run: `31164801056`  
Upstream Gate D1 V2 fingerprint: `fa97d44b44b44ee8b14bfc1d5c42ccea9896e326ca69f2724cec99f90cd0ecc3`

## Why this gate exists

Gate D1 V2 completed successfully and found the exact A2.1 archive, exact A2.1 projection, and authoritative current page 3. Its only missing input is `legacy_a30_page_family`, while `legacy_a30_runs=[]`.

The frozen A3.1 parity boundary still requires the original A3.0 page family with exactly 49 `current` pages and 41 `preview` pages. Gate D2 diagnoses retained A3.0 candidates without weakening or replacing that frozen requirement.

## Diagnostic scope

The tool scans only the retained ALDI shadow state root for bounded A3.0 manifest candidates matching:

- `a30-v02-runs/*/reports/page-image-manifest.json`;
- recursive copies of the same bounded path shape.

For each candidate it reports only sanitized metadata:

- root-relative manifest path;
- manifest regular-file and JSON status;
- current/preview/other row counts;
- duplicate/invalid manifest row counts;
- whether the frozen Gate D manifest contract passes;
- image-root presence;
- missing, byte-mismatch, SHA-mismatch and format-mismatch counts;
- page-set SHA only when the full 49+41 family validates.

Raw page bytes and raw exception strings are never exported.

## Frozen validator binding

The RPi5 installer does not invent a new legacy validator. It requires the immutable Gate D1 V1 bundle:

- V1 commit `690a0a09364b59e323230d24af006542bbdb1012`;
- V1 bundle-manifest SHA256 `481bd9ea014afb928f9f2b4b5d5f84c6f571c72c2524d7b442b16124ca73169f`;
- exact bundled `tools/aldi_weekly_gate_d_visual_review_pack.py` row and bytes/SHA.

The diagnostic therefore inherits the already reviewed frozen 49+41 manifest and image validation contract.

## Decisions

- `EXACT_LEGACY_FAMILY_FOUND`: exactly one distinct complete 49+41 page-set identity validates;
- `NO_VALID_LEGACY_FAMILY`: no retained candidate validates completely;
- `MULTIPLE_VALID_LEGACY_FAMILIES`: more than one distinct complete page-set identity validates and must be resolved explicitly.

A diagnostic PASS does not authorize Gate D review-pack execution or production work.

## Execution boundary

After the implementation PR is squash-merged, synchronize only `/home/andris/hermes-deals-audit-source` to that exact merge SHA and run the root installer:

```bash
sudo python3 /home/andris/hermes-deals-audit-source/tools/runner/install-aldi-gate-d2-legacy-family-diagnostic.py <MERGE_SHA>
```

Then the separately owner-authorized workflow is:

```bash
gh workflow run aldi-gate-d2-legacy-family-diagnostic-rpi5.yml \
  --repo rozkalnsandris/hermes-deals \
  -f pr_number=<MERGED_PR_NUMBER>
```

The RPi5 job performs no repository checkout and calls only the narrow registered root dispatcher.

## Safety

This gate is read-only. It performs no source acquisition, parser execution, candidate creation, corpus mutation, production DB/Review write, approval/publication, deploy, scheduler/retry, canary, or B15M2 V08 action. The frozen 49+41 expectation remains unchanged.
