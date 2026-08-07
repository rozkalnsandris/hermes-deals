# ALDI Gate D3 immutable recovery inventory

Issue: #266

## Upstream evidence

Gate D2 workflow run `31166120424` completed successfully for registered commit `52994faadb26cd1bde48061cb9de4ec62f918d24`.

Its sanitized result is authoritative for this step:

- decision: `NO_VALID_LEGACY_FAMILY`;
- diagnostic fingerprint: `b02a88b0f607b7d2e00eb9ea304a6e9711c55db3655f7f3e3c04b27a4f21a3db`;
- bounded A3.0 manifest candidates: `0`;
- valid 49+41 candidates: `0`.

The absence of the original `a30-v02-runs/*/reports/page-image-manifest.json` tree does not prove that all 90 immutable page bytes were deleted. Gate D3 therefore inventories possible retained recovery sources before any reconstruction is considered.

## Historical A3.0 contract

The A3.0 v02 runner wrote runs under:

`/home/andris/.local/state/hermes-deals/aldi-perfect-shadow/a30-v02-runs/<timestamp>/`

A successful run contained:

- `raw/page-images/current/page-001.img` through page 049;
- `raw/page-images/preview/page-001.img` through page 041;
- `reports/page-image-manifest.json`.

The runner did not automatically create a tar archive of the run.

## What Gate D3 inventories

The inventory is read-only and bounded to:

`/home/andris/.local/state/hermes-deals/aldi-perfect-shadow`

It searches for:

1. any regular non-symlink `page-image-manifest.json`, even when moved outside the original A3.0 directory shape;
2. any directory containing `raw/page-images/current` and `raw/page-images/preview`;
3. any regular `.tar.gz` or `.tgz` retained archive containing an A3.0-like page-image tree or page manifest.

The exact A2.1 archive SHA256 `fa16df4db701e90f38bea0387a278750415ba03628f1fe1cc34ffb2833f2985d` is recognized separately and is never promoted as recovered A3.0 evidence.

## Complete recovery identity

A directory or archive is a complete recovery candidate only when it contains exactly the contiguous frozen page sequence:

- current pages 1..49;
- preview pages 1..41.

Each page must be a regular plausible JPEG, PNG or WebP file of at least 10,000 bytes.

The tool computes a deterministic identity over page label, page number, byte size, SHA256 and image format. It does not create a replacement page manifest in this gate.

## Archive safety

Tar archives are inspected without extraction. Before any member is considered, Gate D3 rejects archives containing:

- absolute or traversing paths;
- duplicate member names;
- symlinks or hardlinks;
- device or FIFO members;
- unsupported member types.

Raw member bytes are read only in memory for SHA/image validation and are never exported.

## Decisions

- `RECOVERY_CANDIDATE_FOUND`: exactly one distinct complete 49+41 identity is retained;
- `NO_RECOVERY_CANDIDATE`: no complete retained 49+41 identity is found;
- `AMBIGUOUS_RECOVERY_CANDIDATES`: more than one distinct complete 49+41 identity is retained.

A positive inventory result does not authorize extraction, manifest regeneration, Gate D review-pack execution or production work. A later recovery-binding gate must verify provenance and bind the chosen immutable page family to the frozen A3.1 contract.

## Post-merge execution

Synchronize only `/home/andris/hermes-deals-audit-source` to the exact squash-merge SHA and install:

```bash
sudo python3 /home/andris/hermes-deals-audit-source/tools/runner/install-aldi-gate-d3-recovery-inventory.py <MERGE_SHA>
```

Then run the separately owner-authorized workflow:

```bash
gh workflow run aldi-gate-d3-recovery-inventory-rpi5.yml \
  --repo rozkalnsandris/hermes-deals \
  -f pr_number=<MERGED_PR_NUMBER>
```

## Safety

Gate D3 performs no network acquisition, archive extraction, source/corpus mutation, page-manifest regeneration, parser execution, candidate creation, Review write, approval/publication, production DB write, deploy, scheduler/retry, production canary or B15M2 V08 action. The frozen 49+41 expectation remains unchanged.
