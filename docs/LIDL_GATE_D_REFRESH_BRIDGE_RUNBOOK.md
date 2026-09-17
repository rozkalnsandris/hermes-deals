# Lidl Gate D dedicated-checkout refresh bridge

Issue #910 adds source-only control-plane code. Merging or installing this source does not itself synchronize the dedicated Lidl checkout, refresh Gate D registration, activate systemd, run Gate D, publish offers, write production data, or deploy production.

## Trust-boundary sequence

1. **Bootstrap registration — separate LIVE authorization.** From an exact, clean primary checkout on merged `main`, register `install-lidl-source-sync-bridge.sh` and `install-lidl-gate-d-registration-refresh-bridge.sh`. Bootstrap must stop after registering the two fixed root-owned dispatchers/configs/sudoers. It must not invoke either dispatcher.
2. **Dedicated checkout sync — separate LIVE authorization.** Manually dispatch `hermes-lidl-source-sync.yml` with the then-current exact `main` SHA. The hosted job requires the allowlisted owner and successful exact-main push CI. The self-hosted job can only invoke `/usr/local/sbin/hermes-deals-lidl-source-sync-dispatch <sha> <runner-temp-dir>`, which fetches only canonical public `refs/heads/main` and updates `/home/andris/hermes-deals-audit-source-lidl` only by fast-forward.
3. **Gate D registration refresh — separate LIVE authorization.** Only after the dedicated checkout is exact-main may `hermes-lidl-gate-d-registration-refresh.yml` be dispatched for the same then-current exact `main` SHA. The fixed dispatcher validates the prior registration, requires its registration SHA to be an ancestor of the target, preserves the validated prior fixed registration files under deterministic retired names when a forward refresh is needed, and invokes only `tools/runner/install_lidl_gate_d_control_nonrewind.py` with the fixed reviewed schedule. It never activates Gate D/systemd/timers.
4. **Activation — separate LIVE authorization.** After the sanitized registration receipt exposes the fresh `target=next` plan fingerprint, revalidate merged source and use the existing `/hermes-lidl gate-d activate ...` owner-control path under a new explicit authorization.

The historical #908 fingerprint `451aabbd432a8776bed70209f966690ab647ac66b69947b77545fc1638e44c9e` is **non-authoritative after #910 source drift** and must not be reused. A fresh Gate D v2 `target=next` fingerprint must come from the exact merged-main registration receipt.

## Fail-closed behavior

No reset, rebase, force update, arbitrary repository path, arbitrary fetch URL/refspec, arbitrary installer, or arbitrary sudo command is accepted. A dispatcher failure after a LIVE mutation begins produces only the bounded sanitized receipt and stops; there is no automatic retry, rollback, cleanup, or alternate mutation path. Any subsequent mutation requires fresh owner authorization and fresh read-only evidence.

**Production deploy: NO.** Production DB/review/publication writes, collector execution, Gate D runtime/replay, retained-evidence mutation, Cloudflare/network/DNS changes, container mutation, and scheduler/systemd activation are outside this bridge's source lane.
