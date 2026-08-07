# Netto geometry RPi5 replay V1

Issue: #95

## Purpose

This control plane runs the already merged `netto_visual_geometry_corpus_replay.py` against the immutable Netto N9/N10 evidence on the RPi5 without activating any production parser.

It exists only to produce reproducible evidence for the next #95 review gate.

## Security design

The workflow follows the current GitHub Actions security guidance for `pull_request_target` and self-hosted runners:

- the privileged `pull_request_target` workflow never checks out or executes pull-request code;
- only the repository owner identity (`rozkalnsandris`, numeric GitHub ID `277435981`) may trigger the replay label;
- the target PR must already be merged into this repository's `main`;
- the exact merge SHA must remain reachable from current `main`;
- that exact merge SHA must have a successful `push` run of `.github/workflows/ci.yml` named `Hermes Deals CI checks`;
- `GITHUB_TOKEN` permissions are declared explicitly and kept read-only except for the narrow label/report jobs;
- the self-hosted runner has no Docker-group membership and may invoke only the dedicated root dispatcher through sudo;
- no PR head or merge ref is checked out on the RPi5;
- the uploaded artifact is produced from a fixed sanitizer allowlist;
- `actions/upload-artifact` is pinned to the full v7.0.1 release commit SHA `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`.

The existing `netto-shadow-v1` dispatcher used by issues #27/#28 is not modified or reused.

## PR validation refresh

Before merge, if `main` has advanced since the latest successful PR CI run, make a scoped head update without widening the five-file Netto diff and require a fresh PR merge-ref CI run against current `main`. An older successful run is evidence for its tested merge state only.

## Exact runtime sources

The installer accepts only this detached worktree:

`/home/andris/hermes-deals-worktrees/netto-geometry-replay-v1`

The worktree must:

- belong to the Git common directory `/home/andris/hermes-deals/.git`;
- use the expected Hermes Deals GitHub origin;
- be detached at the exact registered merge SHA;
- be clean;
- contain a fetched `origin/main` for which the registered SHA is an ancestor.

The primary `/home/andris/hermes-deals` checkout is never switched, reset or cleaned.

### Source-worktree Git ownership boundary

The installer itself runs as root because it installs a root-owned runtime, dispatcher and sudoers rule. The source worktree does **not** belong to root. All source-worktree Git checks run as `andris` through a clean `runuser` environment with `GIT_OPTIONAL_LOCKS=0`.

This is required because `git status` normally performs a background index refresh and may write the worktree index even when the caller only intends to inspect repository state. Running that inspection under sudo can therefore change the index owner to root and break subsequent unprivileged worktree operations. `GIT_OPTIONAL_LOCKS=0` disables optional index-refresh writes, and the exact user boundary ensures Git metadata is always inspected under the worktree owner identity.

A root-owned installer must not directly run `git -C "$SOURCE_REPO" ...` against this worktree. Any future Git inspection added to the installer must go through the same unprivileged helper boundary.

The installer copies the following reviewed inputs into the root-owned runtime tree `/usr/local/libexec/hermes-deals-audits/netto-geometry-replay-v1` and records SHA-256 bindings for every member:

- `tools/run-hermes-deals-netto-geometry-replay-v01.sh`;
- `tools/netto_visual_geometry_corpus_replay.py`;
- `tools/netto_visual_geometry_shadow.py`;
- `backend/tests/fixtures/netto/n10_full_visual_review_v1.json`.

The runtime requires the existing host `/usr/bin/python3` environment to expose exactly `PyMuPDF==1.28.0`. It never installs Python packages.

## Immutable evidence inputs

The unprivileged replay runner accepts only:

- N9 manifest:
  `/home/andris/hermes-deals-audits/netto-n9-visual-cell-validation-pack-v1-20260802T202304Z/generated/fixture-manifest.json`
- N9 manifest SHA256:
  `2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147`
- corpus root:
  `/home/andris/hermes-deals-netto-corpus/flyers`
- N10 ledger SHA256:
  `bf35bff323d76a2b29a7248df067641e5b9f2a7d29329cf53bf9fc0ae832734a`
- geometry parser identity:
  `netto-visual-geometry-shadow-v3-unrotated-page-space`.

The merged replay tool itself verifies both authoritative campaign PDFs, campaign/page counts, N9/N10 identities and all 100 cell bindings.

## Artifact boundary

The dispatcher may export only:

- `netto-geometry-corpus-replay.json`;
- `runtime-identity.json`;
- `replay-execution.log`;
- `replay-exit-code.txt`;
- generated `dispatcher-evidence-manifest.json`.

Every regular file is size-bounded and scanned for common private-key, GitHub-token and PostgreSQL credential patterns before the artifact directory is handed back to `github-runner`.

A successful result must still contain:

- `fixture_page_count=17`;
- `cell_count=100`;
- `second_review_status=replay_evidence_only`;
- `review_only_default=true`;
- `promotion_ready=false`;
- automatic approval/publication disabled;
- no database write;
- no deployment;
- no production apply authorization.

## Controlled installation after merge

Installation is a separate privileged operation and is **not** performed by merging the PR.

From the RPi5:

```bash
PRIMARY=/home/andris/hermes-deals
WORKTREE=/home/andris/hermes-deals-worktrees/netto-geometry-replay-v1
EXPECTED_SHA=<exact-squash-merge-sha>

git -C "$PRIMARY" fetch origin main
git -C "$PRIMARY" merge-base --is-ancestor "$EXPECTED_SHA" origin/main
test ! -e "$WORKTREE"
git -C "$PRIMARY" worktree add --detach "$WORKTREE" "$EXPECTED_SHA"

sudo bash "$WORKTREE/tools/runner/install-netto-geometry-rpi5-replay.sh" \
  "$EXPECTED_SHA" \
  "$WORKTREE"
```

The installer must print `INSTALL_RESULT=PASS`.

Do not install from an unmerged branch, PR head, arbitrary checkout or a worktree with local changes.

## Controlled replay after installation

After the exact merged SHA has a successful `main` push CI run and the root-owned replay has been installed for the same SHA, add this label to that **merged PR**:

`audit:netto-geometry-replay-v1`

The main-branch `pull_request_target` workflow then:

1. validates owner login and numeric identity;
2. validates the merged PR and exact main ancestry;
3. validates exact-SHA `Hermes Deals CI checks` success;
4. invokes the dedicated root-owned dispatcher on `rpi5-hermes-deals-audit`;
5. uploads only sanitized evidence;
6. posts the result to the merged PR and removes the trigger label.

## Non-goals

This replay does not:

- deploy production;
- restart production services;
- use Docker;
- access or write PostgreSQL;
- write Review state;
- approve or publish offers;
- change collectors or schedulers;
- activate the geometry parser;
- authorize field promotion;
- close issue #95.

The artifact is evidence for the next independent review step only.
