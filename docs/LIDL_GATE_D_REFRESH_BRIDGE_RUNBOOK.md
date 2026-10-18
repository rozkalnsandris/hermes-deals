# Lidl Gate D dedicated-checkout refresh bridge

Issue #910 adds source-only control-plane code. Merging or installing this source does not itself synchronize the dedicated Lidl checkout, refresh Gate D registration, activate systemd, run Gate D, publish offers, write production data, or deploy production.

## Trust-boundary sequence

1. **Bootstrap registration — separate LIVE authorization.** From an exact, clean primary checkout on merged `main`, register `install-lidl-source-sync-bridge.sh` and `install-lidl-gate-d-registration-refresh-bridge.sh`. Bootstrap must stop after registering the two fixed root-owned dispatchers/configs/sudoers. It must not invoke either dispatcher.
2. **Dedicated checkout sync — separate LIVE authorization.** Manually dispatch `hermes-lidl-source-sync.yml` with the then-current exact `main` SHA. The hosted job requires the allowlisted owner and successful exact-main push CI. The self-hosted job can only invoke `/usr/local/sbin/hermes-deals-lidl-source-sync-dispatch <sha> <runner-temp-dir>`, which fetches only canonical public `refs/heads/main` and updates `/home/andris/hermes-deals-audit-source-lidl` only by fast-forward.
3. **Gate D registration refresh — separate LIVE authorization.** Only after the dedicated checkout is exact-main may `hermes-lidl-gate-d-registration-refresh.yml` be dispatched for the same then-current exact `main` SHA. The fixed dispatcher validates the prior registration, requires its registration SHA to be an ancestor of the target, preserves the validated prior fixed registration files under deterministic retired names when a forward refresh is needed, and invokes only `tools/runner/install_lidl_gate_d_control_nonrewind.py` with the fixed reviewed schedule. It never activates Gate D/systemd/timers.
4. **Activation — separate LIVE authorization.** After the sanitized registration receipt exposes the fresh `target=next` plan fingerprint, revalidate merged source and use the existing `/hermes-lidl gate-d activate ...` owner-control path under a new explicit authorization.

The historical #908 fingerprint `451aabbd432a8776bed70209f966690ab647ac66b69947b77545fc1638e44c9e` is **non-authoritative after #910 source drift** and must not be reused. A fresh Gate D v2 `target=next` fingerprint must come from the exact merged-main registration receipt.

## Pre-retirement validation and partial-state recovery

The registration dispatcher must run the exact-source/target=`next` installer with `--preflight-only` and validate its receipt **before** moving an existing registered dispatcher, config, or sudoers file. This preflight must not install files, change the timer/service, or execute Gate D. A stale runtime Git blob is a blocked preflight, not a reason to retire the previous registration.

A failed earlier refresh can leave the original root registration in deterministic `retired-...` paths with no active Gate D control registration. **Do not rerun the normal refresh, move retired files back, or activate the timer as a recovery shortcut.** Verify the exact current host state read-only; design and request a separate scope-limited owner LIVE authorization for recovery only after the corrected source is merged and synchronized.

## Exact observed legacy service migration

Issue #906 read-only evidence on 2026-10-18 identified an installed `hermes-lidl-weekly.service` with SHA-256 `228d32d26ed6cd5cc76b5a4cfab347a7249c5b316065b23f8174f24f09ef8d77`. Compared with the earlier reviewed service, only the `ExecStart` checkout SHA differs. Migration accepts **only** this service digest paired with the original exact timer and failure-template digests, or the original fully attested legacy triplet. All installed units must be root-owned regular files, mode 0644.

Backups use the SHA-256 of each **actually installed** legacy unit. A pre-existing backup may be reused only when it is the exact expected regular root-owned mode-0644 file and its SHA-256 matches the installed legacy unit; it is preserved byte-for-byte and never overwritten. Unknown/mixed backup content, unsafe backup metadata, drop-ins, a running service, stale checkout SHA or file drift block before first migration mutation. This source fix does not authorize host registration or activation; new explicit LIVE gates and fresh exact-head evidence remain required.

## Fail-closed behavior

No reset, rebase, force update, arbitrary repository path, arbitrary fetch URL/refspec, arbitrary installer, or arbitrary sudo command is accepted. A dispatcher failure after a LIVE mutation begins produces only the bounded sanitized receipt and stops; there is no automatic retry, rollback, cleanup, or alternate mutation path. Any subsequent mutation requires fresh owner authorization and fresh read-only evidence.

**Production deploy: NO.** Production DB/review/publication writes, collector execution, Gate D runtime/replay, retained-evidence mutation, Cloudflare/network/DNS changes, container mutation, and scheduler/systemd activation are outside this bridge's source lane.
