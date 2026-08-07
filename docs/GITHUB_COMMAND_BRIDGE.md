# GitHub command bridge

## Purpose

The Hermes Deals command bridge lets an owner-authenticated GitHub issue comment invoke a narrowly allowlisted operational audit without exposing arbitrary shell execution or broad GitHub Actions write authority to ChatGPT.

The bridge exists because the ChatGPT GitHub connector can create issue comments but does not expose the GitHub `workflow_dispatch` action directly.

## Trust boundary

The bridge is intentionally fail-closed.

A command is accepted only when all of the following are true:

- repository is exactly `rozkalnsandris/hermes-deals`;
- the GitHub event sender login is exactly `rozkalnsandris`;
- the sender numeric GitHub ID is exactly `277435981`;
- the comment is on an issue, not a pull request;
- the entire stripped comment matches one allowlisted command grammar;
- the referenced runtime PR is already merged into this repository's `main`;
- the merged runtime SHA is still reachable from current `main`;
- every command field passes strict type/value validation before reaching the self-hosted runner.

Raw issue-comment text is never passed to the RPi5 shell.

## V1 allowlist

V1 exposes exactly one operation:

```text
/hermes-bridge lidl-gate-a pr=<merged-pr> target=<current|next> as_of=<YYYY-MM-DD> use_previous=<true|false>
```

Example:

```text
/hermes-bridge lidl-gate-a pr=299 target=current as_of=2026-08-07 use_previous=false
```

No aliases, extra fields, extra lines, shell operators or trailing commands are accepted.

## Execution path

1. `.github/workflows/hermes-command-bridge.yml` receives an `issue_comment.created` event.
2. A GitHub-hosted authorization job checks out the default-branch bridge code with credentials disabled.
3. `tools/github_command_bridge.py` validates owner identity, exact command grammar, date, merged PR and current-main reachability.
4. Only normalized validated outputs are passed to the self-hosted RPi5 job.
5. The RPi5 job invokes only the pre-existing fixed root-owned dispatcher:

   ```text
   /usr/local/sbin/hermes-deals-lidl-weekly-gate-a-dispatch
   ```

6. The dispatcher remains responsible for registered SHA/image validation, evidence sanitization and the existing Gate A safety contract.
7. Only sanitized evidence is uploaded as a GitHub Actions artifact.
8. The workflow posts a sanitized result comment back to the issue that carried the command.

The report comment cannot recursively execute the bridge because it does not match the command grammar and is not authored by the allowlisted owner identity.

## Safety contract

V1 never authorizes:

- corpus writes;
- production database writes;
- Review writes, approval or publication;
- production deploy/restart;
- systemd or timer changes;
- automatic retry;
- arbitrary shell commands.

The RPi5 result is rejected if any corresponding Gate A authority flag is not exactly `false`.

## Extending the bridge

Adding another operation requires a normal reviewed code change. New commands must have:

- an exact parser/grammar;
- explicit owner and repository binding;
- a narrow pre-existing dispatcher or similarly bounded execution surface;
- negative injection tests;
- explicit safety flags and sanitized evidence;
- no generic `command`, `script`, `args`, `shell`, `eval`, `bash -c` or equivalent escape hatch.

Do not turn this bridge into a general-purpose remote shell or generic workflow dispatcher.
