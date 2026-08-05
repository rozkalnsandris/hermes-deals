# Netto RPi5 shadow audit — worktree ownership repair v2

The first isolated installation completed successfully, but the root-run v1 installer executed `git status` against the dedicated linked worktree. Git may refresh and atomically replace a linked-worktree index during `git status`; when run as root, that replacement can become root-owned.

The v2 wrapper is restricted to:

- `/home/andris/hermes-deals-worktrees/netto-shadow-audit-install`;
- `/home/andris/hermes-deals/.git/worktrees/netto-shadow-audit-install`.

Before changing ownership it verifies the exact `.git` pointer, `commondir` and reverse `gitdir` binding. It then repairs only that dedicated administrative directory, exports `GIT_OPTIONAL_LOCKS=0` for the inherited v1 installer, and validates the final repository state as the unprivileged `andris` user.

The wrapper does not modify the primary B15M2 checkout, Docker, PostgreSQL, application data, deployments, approvals or publication state.
