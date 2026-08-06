# Netto N10 exact import and reconciliation V1

Issue: #95

This step imports the already completed independent N10 100-cell visual-review
ledger into a dedicated Git worktree and generates a deterministic reconciliation
report against the merged first-pass visual shadow corpus.

It does not change the Netto parser, production database, Review Queue, runtime,
scheduler, approval state or publication state.

## Authoritative source binding

The importer accepts only the original N10 ledger with:

- raw SHA256: `bf35bff323d76a2b29a7248df067641e5b9f2a7d29329cf53bf9fc0ae832734a`;
- raw size: `104385` bytes;
- N9 fixture manifest SHA256: `2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147`;
- 17 reviewed pages;
- 100 reviewed cells;
- campaign counts `hz31_hasb_4=26` and `hz32_hasb=74`;
- 98 target/review cells and 2 scope controls;
- visual indexes exactly `1..100`;
- automatic approval, automatic publication and production writes disabled.

The original N10 run independently recorded all focused contract tests as PASS,
`SCRIPT_EXIT_RC=0`, no production source change, no database write and no deploy.

## Supported source forms

Use exactly one source:

1. the existing shadow ledger:

   ```text
   /home/andris/hermes-deals-netto-shadow/backend/tests/fixtures/netto/n9_full_visual_review_v1.json
   ```

2. the original builder script:

   ```text
   /home/andris/build-hermes-deals-netto-n10-full-visual-truth-baseline-v1.sh
   ```

For the builder form, the importer extracts only the unique `JSON_LEDGER`
heredoc. The extracted bytes must still match the authoritative SHA and size.

## Controlled worktree run

Do not run the import in the primary `/home/andris/hermes-deals` worktree.
After this importer has been merged, use a separate branch and worktree:

```bash
REPO=/home/andris/hermes-deals
WT=/home/andris/hermes-deals-worktrees/netto-n10-ledger-import
BRANCH=fix/95-netto-n10-ledger-evidence

git -C "$REPO" fetch origin main
git -C "$REPO" worktree add -b "$BRANCH" "$WT" origin/main

cd "$WT"
python3 tools/netto_n10_import_and_reconcile.py \
  --ledger /home/andris/hermes-deals-netto-shadow/backend/tests/fixtures/netto/n9_full_visual_review_v1.json \
  --first-review backend/tests/fixtures/netto/visual_cell_shadow_corpus_v1.json \
  --import-destination backend/tests/fixtures/netto/n10_full_visual_review_v1.json \
  --report backend/tests/fixtures/netto/n10_visual_review_reconciliation_v1.json
```

Fallback when only the original builder exists:

```bash
python3 tools/netto_n10_import_and_reconcile.py \
  --builder-script /home/andris/build-hermes-deals-netto-n10-full-visual-truth-baseline-v1.sh \
  --first-review backend/tests/fixtures/netto/visual_cell_shadow_corpus_v1.json \
  --import-destination backend/tests/fixtures/netto/n10_full_visual_review_v1.json \
  --report backend/tests/fixtures/netto/n10_visual_review_reconciliation_v1.json
```

## Required post-run checks

```bash
sha256sum backend/tests/fixtures/netto/n10_full_visual_review_v1.json
python3 -m json.tool \
  backend/tests/fixtures/netto/n10_visual_review_reconciliation_v1.json \
  >/dev/null
cd backend
python3 -m unittest -v \
  tests.test_netto_visual_review_reconciliation \
  tests.test_netto_n10_import_and_reconcile
```

The imported ledger SHA must be exactly:

```text
bf35bff323d76a2b29a7248df067641e5b9f2a7d29329cf53bf9fc0ae832734a
```

The report must retain:

- `identity_match_count=100`;
- explicit title and price disagreement lists;
- `promotion_ready=false`;
- automatic approval and publication disabled;
- database write, deploy and parser activation false.

A disagreement is evidence for adjudication, not permission to overwrite either
review. Even a fully consistent result remains fail-closed until a later,
separately reviewed parser-promotion decision.

## Commit scope after a successful run

Only these generated evidence files belong in the follow-up PR:

```text
backend/tests/fixtures/netto/n10_full_visual_review_v1.json
backend/tests/fixtures/netto/n10_visual_review_reconciliation_v1.json
```

No production deploy is required for either the importer PR or the later
evidence-only import PR.
