# VS Code controlled RPi5 release

Use these tasks only from the RPi5 Remote SSH window with the Hermes Deals primary repository open on `main`.

1. Run `Hermes Deals: Check deploy`.
2. Run `Hermes Deals: Plan production deploy` and require PASS.
3. Review the GitHub Actions result and evidence.
4. Run `Hermes Deals: Apply production deploy` only after explicit owner approval.
5. Type the exact SHA-bound confirmation shown in the terminal.

The launcher refuses dirty worktrees, non-main branches, unsynchronized local/remote main, commits not bound to exactly one merged PR, and database migrations. It reuses the existing root-owned controlled API/UI release workflow and does not replace its authorization, CI, exact-SHA, runner, evidence, or rollback gates.

The `Check deploy` task is read-only. `Plan production deploy` registers and verifies the exact release without applying production. `Apply production deploy` is the only task that may change production.
