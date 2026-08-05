# ALDI A3.0 authoritative-cycle acquisition

This audit consumes the current and preview source descriptors proven by GitHub Actions run `31010778804` at commit `24d1a44df06751fe9107e568ceb12c9f2c5cea79`.

It downloads current and preview sequentially until two consecutive terminal failures, verifies every saved page by SHA256, and compares the newly acquired current against the immutable 41-page preview evidence from the prior cycle.

## Strict promotion gate

PASS still requires:

- current exactly 41 pages;
- preview at least one complete page and a proven terminal boundary;
- distinct current and preview source paths;
- all 41 current pages visually matching the old preview within frozen thresholds;
- no production database write, deployment, collector, approval or publication.

The manual-review analysis does **not** weaken this gate.

## Controlled rollover analysis

When positional 41/41 comparison fails, the artifact also records:

- positional visual matches;
- exact same-position content matches;
- exact content-set matches independent of page position;
- deterministic old-page to new-page mappings for identical moved pages;
- old-only and new-only pages;
- duplicate-content groups, if any;
- cross-comparison metrics for unmatched page candidates.

The artifact contains:

```text
manual-review/manual-review.json
manual-review/index.html
manual-review/old-preview/
manual-review/new-current/
```

Only unmatched old-preview and new-current pages are copied into the manual-review directories. Identical moved pages remain represented by their SHA256 mapping and are not duplicated into the review set.

The first authoritative-cycle run `31028504897` established the reference classification:

```text
current pages: 41
preview pages: 41
positional visual matches: 36/41
exact content-set matches: 39/41
moved identical pages: 3->4, 4->5, 5->37
old-only pages: 37, 41
new-only pages: 3, 41
```

This remains a controlled `REVIEW_REQUIRED` result and does not authorize source promotion.

## Fail-closed worktree verification

The RPi5 runner captures independent before/after snapshots of both:

- `/home/andris/hermes-deals-audit-source`;
- `/home/andris/hermes-deals`.

Each snapshot verifies:

- canonical Git directory;
- readable, regular, non-symlink Git index;
- absent index lock;
- branch and HEAD;
- porcelain status bytes;
- Git index SHA256 and metadata;
- empty Git stderr for every command.

Any command failure **or any Git stderr output** blocks the audit. A failed verification reports:

```text
PRIMARY_WORKTREE_VERIFICATION=failed
PRIMARY_WORKTREE_MODIFIED=unknown
```

It must never claim `PRIMARY_WORKTREE_MODIFIED=false` after an unreadable index or another incomplete check.

## Installer index-ownership contract

The authoritative-cycle installer runs as root only to write the registered script, dispatcher, configuration and sudoers rule. It must not run Git directly as root inside `/home/andris/hermes-deals-audit-source`.

All installer Git verification is executed through:

```text
runuser -u andris
HOME=/home/andris
GIT_OPTIONAL_LOCKS=0
```

The installer captures the audit repository index owner, mode, byte size and SHA256 before Git verification. It checks the same values after Git verification and again after all root-owned installation work.

Installation is blocked when:

- `.git/index` is missing, a symlink or locked;
- the index owner is not `andris:andris`;
- the index is not readable and writable by `andris`;
- a Git command fails or emits stderr;
- index ownership, mode, size or content changes during installer execution.

A successful installer reports:

```text
INSTALLER_INDEX_OWNERSHIP_PRESERVED=true
```

This contract prevents root installer verification from recreating the historical `root:root 0600` audit index and breaking the next owner-run synchronization or RPi5 audit.

## Registration and execution

After merge, synchronize `/home/andris/hermes-deals-audit-source` to the squash-merge SHA and run:

```bash
sudo bash tools/runner/install-aldi-a30-authoritative-cycle-dispatcher.sh <MERGE_SHA>
```

Then run **ALDI A3.0 authoritative cycle RPi5** with the merged PR number. The self-hosted runner executes only the root-owned script registered to the exact merge SHA and uploads sanitized evidence as a GitHub Actions artifact.

Production DB writes, deployment, collector execution, approval, publication and B15M2 V08 actions remain outside this workflow.
