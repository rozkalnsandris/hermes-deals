# EDEKA production canary dispatcher forward registration

## Purpose

The original checksum-bound EDEKA root registration is intentionally append-only. After PR #669 changed the global dispatcher blob from:

- predecessor: `f4c54c91ded3edcd631f3e83f37a54229dfb2413`
- target: `95339e076907e43eb2307fce66f4768a60ef2296`

a host that already contains the predecessor dispatcher cannot use the original installer directly because `write_exclusive_or_identical()` correctly rejects different bytes.

`tools/runner/install_edeka_production_canary_control_forward_nonrewind.py` is a narrow forward bridge for this one transition.

## Security contract

The forward bridge:

- must run as root from `/home/andris/hermes-deals-audit-source-edeka`;
- requires the dedicated clone to be clean, on `main`, and have both `HEAD` and `origin/main` equal the requested registration SHA;
- verifies its own bytes come from that exact commit;
- verifies the existing registration installer blob is exactly `4285d3b1bdbaeddfc2d6698a96cb91c40f7d7946`;
- verifies the target dispatcher blob is exactly `95339e076907e43eb2307fce66f4768a60ef2296`;
- accepts the global dispatcher only when it is absent, already the target, or exactly the approved predecessor `f4c54c91ded3edcd631f3e83f37a54229dfb2413`;
- rejects unknown dispatcher bytes and does not provide a generic predecessor allowlist;
- writes the target to a root-owned `0755` temporary file in the same directory, fsyncs it, re-checks the predecessor inode/metadata state, then uses `os.replace()` for the atomic forward replacement and fsyncs the directory;
- after the dispatcher is target-identical, invokes the existing checksum-bound non-rewind registration installer for the same exact SHA;
- never executes canary `verify`, `apply`, `replay`, or `rollback`;
- never performs a production DB write, source refetch, Review/publication write, scheduler/systemd change, or production deploy.

If the downstream registration installer fails after the dispatcher has advanced, rerunning the same exact wrapper is safe: it sees the target dispatcher as identical and retries only the normal registration.

## Owner gate

Merging the source change does not authorize host mutation.

After merge and exact-main CI success, obtain a new explicit owner authorization bound to the new merge SHA before executing:

```bash
sudo -- /usr/bin/python3 \
  /home/andris/hermes-deals-audit-source-edeka/tools/runner/install_edeka_production_canary_control_forward_nonrewind.py \
  --registration-sha <EXACT_MAIN_SHA>
```

Successful registration still does not authorize canary `verify` or `apply`.
