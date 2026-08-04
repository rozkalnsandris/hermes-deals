# Netto shadow RPi5 audit installation checklist v1

This checklist is intentionally separate from the audit implementation. It is
used only after the implementation PR is merged and its exact squash-merge SHA
is known.

1. Synchronize `/home/andris/hermes-deals` to `origin/main`.
2. Confirm branch `main`, exact expected HEAD and a clean worktree.
3. Run `sudo bash tools/runner/install-netto-shadow-rpi5-audit.sh <MERGE_SHA>`.
4. Confirm `INSTALL_RESULT=PASS`, `RUNNER_HAS_DOCKER_GROUP=false` and
   `PRODUCTION_APPLY_AUTHORIZED=false`.
5. Add `audit:netto-shadow-v1` only to the merged implementation PR.
6. Inspect the workflow result, sanitized artifact manifest and audit summary.
7. Keep issues #27 and #28 open when `acceptance_status=blocked`; use the
   blocking reasons to define the next narrow evidence task.

No production deployment, database write, automatic approval or automatic
publication is authorized by this checklist.
