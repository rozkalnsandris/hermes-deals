# EDEKA Patzer weekly shadow-cycle runbook

This runbook captures one real EDEKA Patzer weekly source cycle without using the production database or changing the primary Hermes Deals worktree.

## Safety model

The capture runs from the isolated clone:

```text
/home/andris/hermes-deals-audit-source
```

It writes only to:

```text
/home/andris/hermes-deals-shadow-evidence/edeka
/home/andris/.cache/hermes-deals-edeka-shadow
```

The capture:

- requires exact clean `main` at the registered squash-merge SHA;
- accepts only the allowlisted `rozkalnsandris/hermes-deals` origin;
- requires the exact EDEKA Patzer market identity `071897` / `587881`;
- fetches only `https://www.edeka.de/maerkte/071897/angebote/`;
- creates a new isolated SQLite database for every run;
- writes the full parsed batch once and verifies identical replay writes zero rows;
- produces immutable manifest, raw HTML, normalization report, SQLite evidence and SHA-256 indexes;
- compares the primary worktree branch, HEAD and status before and after the run;
- does not deploy, use Docker, activate systemd, seed Review or publish offers.

## Prepare the isolated clone

Run these commands as `andris` after the shadow-capture pull request has been squash-merged:

```bash
PRIMARY=/home/andris/hermes-deals
AUDIT_REPO=/home/andris/hermes-deals-audit-source
CAPTURE_SHA=<SHADOW_CAPTURE_SQUASH_MERGE_SHA>

if [[ ! -d "$AUDIT_REPO/.git" ]]; then
  git clone --no-hardlinks "$PRIMARY" "$AUDIT_REPO"
  git -C "$AUDIT_REPO" remote set-url origin \
    https://github.com/rozkalnsandris/hermes-deals.git
fi

git -C "$AUDIT_REPO" fetch origin main
git -C "$AUDIT_REPO" switch -C main "$CAPTURE_SHA"

test "$(git -C "$AUDIT_REPO" rev-parse HEAD)" = "$CAPTURE_SHA"
test "$(git -C "$AUDIT_REPO" branch --show-current)" = main
test -z "$(git -C "$AUDIT_REPO" status --porcelain)"
```

These commands operate only on the isolated clone. Do not switch, reset, stash or clean `/home/andris/hermes-deals`.

## Capture one weekly cycle

Run as `andris`:

```bash
bash "$AUDIT_REPO/tools/run-hermes-deals-edeka-shadow-cycle-v01.sh" \
  "$CAPTURE_SHA"
```

A successful run ends with markers similar to:

```text
RESULT=PASS
RUNNER_VERSION=edeka-shadow-cycle-v01
REGISTERED_COMMIT=<exact SHA>
EVIDENCE_DIR=/home/andris/hermes-deals-shadow-evidence/edeka/<timestamp>-<sha-prefix>
ARCHIVE=/home/andris/hermes-deals-shadow-evidence/edeka/hermes-deals-edeka-shadow-<timestamp>-<sha-prefix>.tar.gz
ARCHIVE_SHA256=<64 lowercase hexadecimal characters>
PRIMARY_WORKTREE_MODIFIED=false
PRODUCTION_DATABASE_WRITE=false
PRODUCTION_DEPLOYMENT=false
SCHEDULER_ACTIVATION=false
```

The first run may create a requirements-SHA-bound virtual environment under the cache root. That environment is not used by production services.

## Verify the archive

```bash
sha256sum --check \
  /home/andris/hermes-deals-shadow-evidence/edeka/hermes-deals-edeka-shadow-*.tar.gz.sha256
```

Inside each run directory, both SHA indexes must pass:

```bash
RUN_DIR=<EVIDENCE_DIR_FROM_OUTPUT>
(
  cd "$RUN_DIR/cycle"
  sha256sum --check --strict SHA256SUMS
)
(
  cd "$RUN_DIR"
  sha256sum --check --strict SHA256SUMS
)
```

## Required two-cycle sequence

Issue #26 requires two real consecutive weekly campaigns. Capture the first current campaign, then capture the next campaign after its validity window advances by exactly seven days.

Do not represent two captures of the same campaign as two cycles. The final ledger requires:

- distinct snapshot IDs;
- distinct manifest SHA-256 values;
- distinct raw HTML SHA-256 values;
- campaign starts exactly seven days apart;
- identical parser and normalizer versions;
- at least 150 offers in each cycle;
- every removed source-offer ID explicitly enumerated;
- no unexplained data loss;
- identical snapshot replay delta equal to zero.

After both real cycle directories exist, use `app.edeka_shadow_ledger` to create the final deterministic ledger. The manifest path and SHA are recorded in each `cycle/cycle-evidence.json` file.

## Not authorized by this runbook

This runbook does not authorize:

- production database writes;
- deployment or container replacement;
- systemd timer installation or activation;
- creation of the `edeka-scheduler-armed` file;
- Review Queue seeding or decisions;
- offer publication;
- production canary apply.

Production canary preparation and apply remain separate reviewed and explicitly authorized steps.
