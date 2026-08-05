# ALDI A3.0 authoritative-cycle acquisition

This audit consumes the current and preview source descriptors proven by GitHub Actions run `31010778804` at commit `24d1a44df06751fe9107e568ceb12c9f2c5cea79`.

It downloads current and preview sequentially until two consecutive terminal failures, verifies every saved page by SHA256, and compares the newly acquired current against the immutable 41-page preview evidence from the prior cycle.

PASS requires:

- current exactly 41 pages;
- preview at least one complete page and a proven terminal boundary;
- distinct current and preview source paths;
- all 41 current pages visually matching the old preview within frozen thresholds;
- no production database write, deployment, collector, approval or publication.

A controlled `REVIEW_REQUIRED` result preserves the acquired page files and comparison metrics but does not promote a source.

After merge, synchronize `/home/andris/hermes-deals-audit-source` to the squash-merge SHA and run:

```bash
sudo bash tools/runner/install-aldi-a30-authoritative-cycle-dispatcher.sh <MERGE_SHA>
```

Then run **ALDI A3.0 authoritative cycle RPi5** with the merged PR number. The self-hosted runner executes only the root-owned script registered to the exact merge SHA and uploads sanitized evidence as a GitHub Actions artifact.

Production DB writes, deployment, collector execution, approval, publication and B15M2 V08 actions remain outside this workflow.
