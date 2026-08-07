# ALDI Gate D1 RPi5 exact-evidence discovery execution

This step executes the merged Gate D1 discovery planner against retained ALDI shadow state on the RPi5. It is discovery only. It does not create the Gate D review pack and it does not run a parser, create candidates, write Review/production data, deploy, schedule work, or authorize B15M2 V08.

## Purpose

Gate D needs exact local frozen inputs. Repository code knows their immutable hashes, but it must not guess which retained RPi5 paths contain them. The execution boundary therefore:

1. registers one merged GitHub commit;
2. freezes the complete validator dependency bundle under a commit-addressed root-owned directory;
3. runs only the merged discovery tool as user `andris` against `/home/andris/.local/state/hermes-deals/aldi-perfect-shadow`;
4. exports only a sanitized JSON discovery result and hashes, never the raw frozen evidence;
5. returns one of:
   - `READY_FOR_GATE_D_EXECUTION`;
   - `WAIT_FOR_EXACT_EVIDENCE`;
   - `BLOCKED_AMBIGUOUS_LEGACY_EVIDENCE`.

`READY_FOR_GATE_D_EXECUTION` is still not permission to generate or adjudicate the review pack. That remains a later owner-authorized action.

## Frozen validator bundle

The installer copies the exact merged versions of:

- `tools/aldi_gate_d_rpi5_evidence_discovery.py`;
- `tools/aldi_weekly_gate_d_visual_review_pack.py`;
- `tools/aldi_weekly_gate_c_shadow_replay_preflight.py`;
- `tools/aldi_weekly_gate_c_shadow_replay_preflight_core.py`;
- the Gate B replay-plan index;
- all eight bounded Gate B Base64 fragments.

Every file is hashed in `bundle-manifest.json`. The root dispatcher verifies the manifest and every bundled file before each run. Later movement of `/home/andris/hermes-deals-audit-source` therefore cannot silently change an already registered execution.

## Installer boundary

The installer requires:

- root execution;
- `/home/andris/hermes-deals-audit-source` on `main` at the exact squash-merge SHA;
- a clean audit repository;
- no `.git/index.lock`;
- the audit index to remain byte-identical before and after all verification/installation work;
- Git verification to run as `andris` with `GIT_OPTIONAL_LOCKS=0`;
- an active `hermes-deals-audit` runner;
- `github-runner` not to belong to the Docker group.

The installer performs no `checkout`, `switch`, `reset`, `stash`, `clean`, `fetch`, `pull`, `merge`, or `rebase` operation.

After this PR is squash-merged and the separate audit clone has already been synchronized to that exact merge SHA, installation is:

```bash
sudo python3 /home/andris/hermes-deals-audit-source/tools/runner/install-aldi-gate-d1-evidence-discovery-dispatcher.py <MERGE_SHA>
```

Do not run the installer from `/home/andris/hermes-deals` and do not alter the protected primary worktree for this step.

## GitHub workflow

After the exact dispatcher registration is installed, run:

```bash
gh workflow run aldi-gate-d1-evidence-discovery-rpi5.yml \
  --repo rozkalnsandris/hermes-deals \
  -f pr_number=<MERGED_PR_NUMBER>
```

The workflow authorizer requires the allowlisted owner login and numeric GitHub actor ID, a PR squash-merged into `main`, and a registered merge SHA that is still an ancestor of current `main`.

The RPi5 job uses only the `self-hosted`, `Linux`, `ARM64`, `hermes-deals-audit` runner labels and invokes the narrow root dispatcher. No repository checkout is performed on the RPi5 job.

## Artifact contract

The uploaded artifact contains only:

- `discovery-result.json`;
- `discovery-exit-code.txt`;
- `dispatcher-evidence-manifest.json`;
- `runner-dispatch-exit-code.txt`.

It never exports the A2.1 archive, A2.1 projection, legacy 90-page image corpus, authoritative page 3, database data, or Review data.

The dispatcher rejects any discovery result that:

- contains an absolute or parent-traversing selected/match path;
- claims production eligibility;
- claims Gate D review-pack execution authorization;
- enables parser, network, source mutation, candidate creation, DB/Review write, automatic approval/publication, deploy, scheduler/retry, canary, or B15M2 V08 authority;
- weakens the strict ALDI `41/41` automatic-promotion gate.

## Next step

If the result is `READY_FOR_GATE_D_EXECUTION`, use the selected root-relative evidence paths only in a separately reviewed exact-SHA Gate D review-pack execution step. If the result is WAIT or BLOCKED, resolve the stated evidence condition first; do not substitute a different corpus or infer missing evidence as zero offers.
