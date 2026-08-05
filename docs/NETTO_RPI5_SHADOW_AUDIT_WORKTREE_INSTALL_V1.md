# Netto RPi5 shadow audit — isolated worktree install v1

## Why this path exists

The primary checkout `/home/andris/hermes-deals` may legitimately be reserved for a separate controlled task. The Netto audit must not switch that checkout, remove untracked files or disturb its current branch.

The dedicated installer therefore accepts only this exact source worktree:

`/home/andris/hermes-deals-worktrees/netto-shadow-audit-install`

The worktree must:

- belong to the primary Hermes Deals Git repository;
- use the exact GitHub origin;
- be on branch `main`;
- be clean;
- have the exact registered commit as `HEAD`.

## Installation sequence

Create or refresh the dedicated worktree from the primary repository while leaving the primary checkout untouched:

```bash
PRIMARY=/home/andris/hermes-deals
WORKTREE=/home/andris/hermes-deals-worktrees/netto-shadow-audit-install
EXPECTED_SHA=<exact-main-sha>

git -C "$PRIMARY" fetch origin main
test "$(git -C "$PRIMARY" rev-parse origin/main)" = "$EXPECTED_SHA"
test ! -e "$WORKTREE"
git -C "$PRIMARY" branch -f main "$EXPECTED_SHA"
git -C "$PRIMARY" worktree add "$WORKTREE" main

sudo bash "$WORKTREE/tools/runner/install-netto-shadow-rpi5-audit-worktree.sh" \
  "$EXPECTED_SHA" \
  "$WORKTREE"
```

Do not remove the dedicated worktree after installation. The registered audit runner uses it as the immutable source checkout for code and policy fixtures. Runtime Netto evidence continues to be read from the existing bounded audit and `data/raw` locations.

## Safety boundary

The installer performs deterministic, exact single-occurrence transformations only:

- the base installer registration source becomes the dedicated worktree;
- the installed audit runner reads code from that same worktree;
- the installed Python audit accepts only that exact worktree path.

The generated root-owned runner and tool receive fresh SHA-256 bindings in the existing root-owned audit registry. The GitHub runner still cannot use Docker, PostgreSQL, deployment, approval or publication paths.

The primary checkout branch, untracked B15M2 V08 script and working-tree contents are never modified.
