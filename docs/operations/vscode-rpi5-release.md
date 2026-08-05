# VS Code controlled RPi5 release

Use these tasks only from the RPi5 Remote SSH window with the primary repository `/home/andris/hermes-deals` open on clean synchronized `main`.

1. Run `Hermes Deals: Check deploy`.
2. Review the cumulative release range from the running production SHA to exact current `main`.
3. Run `Hermes Deals: Plan production deploy` and require the bridge request to finish with `hermes:deploy-pass`.
4. Review the GitHub issue, workflow result and sanitized evidence.
5. Run `Hermes Deals: Apply production deploy` only after explicit owner approval and type the exact SHA-bound confirmation shown in the terminal.

The launcher derives the current production SHA from the release-bound API image and checks the complete cumulative diff to current `main`, not only the latest PR. It refuses dirty worktrees, non-main branches, another repository path, unsynchronized local/remote main, a current main commit not bound to exactly one merged PR, unresolved source issues, cumulative database migration changes and cumulative Compose changes.

Plan and apply create owner-authored `hermes:deploy-ready` requests for the existing no-agent release bridge. The bridge performs root auto-registration, exact-main CI verification, immutable image build and testing, plan evidence, apply authorization, API-only recreation, health/UI checks and automatic rollback. VS Code does not dispatch the release workflow directly and never authorizes database writes.

`Check deploy` is read-only. `Plan production deploy` registers and verifies the exact cumulative release without applying production. `Apply production deploy` is the only task that may change production.
