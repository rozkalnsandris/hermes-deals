# Kaufland K3C post-#799 registration re-anchor

Refs: #800, #799, #798, #797, #749, #702.

## Why a new anchor is required

PR #799 merged as `238e6a865d53afebe2d9326cc4e4935d36a3c936` and changed trusted source `tools/runner/kaufland_k3c_promo_structure_bridge_validator.py`. It did not change the K3C workflow or installer, so that merge cannot be used as a registration SHA under the existing control-plane rule.

The prior #797 registration/runtime/root-registration chain is therefore obsolete for any future diagnostic after #799.

## Re-anchor contract

The reviewed re-anchor updates `.github/workflows/kaufland-k3c-promo-structure-rpi5.yml` so receipt inspection binds the bounded sanitizer failure taxonomy introduced by #799.

A reason beginning with `SANITIZER_` is accepted only when it is one of:

- `SANITIZER_PRICE_CLASS_REJECTED`;
- `SANITIZER_LOCATOR_REJECTED`;
- `SANITIZER_IDENTITY_REJECTED`;
- `SANITIZER_SCHEMA_REJECTED`;
- `SANITIZER_BOUND_REJECTED`;
- `SANITIZER_INPUT_READ_REJECTED`;
- `SANITIZER_OUTPUT_REJECTED`.

Any other `SANITIZER_*` code is rejected fail-closed by workflow receipt inspection. This does not relax validator acceptance and does not reinterpret sanitizer-blocked output as structural evidence.

## After merge

Only the exact eventual single-parent squash merge that contains this workflow change may serve as the next registration SHA, after fresh exact-main validation.

Then follow the existing separately authorized sequence:

`source sync -> read-only host preflight -> runtime build -> root registration -> diagnostic`

Do not reuse the #797 runtime candidate, root registration or prior diagnostic authorization.

## Safety

This source-only re-anchor performs no diagnostic replay, retained-evidence read/write, source sync, runtime build, root registration, host mutation, production DB/Review/publication write, scheduler/systemd/container/Cloudflare mutation or deploy.
