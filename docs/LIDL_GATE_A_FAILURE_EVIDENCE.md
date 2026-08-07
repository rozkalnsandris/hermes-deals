# Lidl Gate A early-failure evidence

Issue: #295

The Lidl weekly Gate A dispatcher must fail closed without losing the only useful evidence when the trusted RPi5 runner stops before its normal sanitized output is complete.

## Normal evidence

A normal `READY`, `NO_OP`, `WAIT` or controller-generated `BLOCKED` run continues to export only:

- `gate-a-summary.json`;
- `safety-result.txt`;
- `run-request.txt`;
- `runner-exit-code.txt`;
- `dispatcher-evidence-manifest.json`.

The raw `runner.log`, source PDF/JSON and controller execution log are never uploaded.

## Synthetic fail-closed evidence

After the dispatcher has validated its registration, image identity and GitHub runner artifact directory, it emits a bounded synthetic `BLOCKED` package when one of these fixed conditions occurs:

- a stale Gate A run or dispatcher staging directory already exists;
- the inner runner does not produce a safe `sanitized-summary.json`;
- the inner runner does not produce a safe `safety-result.txt`;
- the inner runner does not produce a safe `run-request.txt`;
- the normal sanitized evidence fails dispatcher validation.

The synthetic package records only fixed allowlisted stage/reason values, the exact requested commit/target/date/previous flag, the registered image identity and the original inner-runner exit code when one exists. The dispatcher returns exit code `30`, so the existing workflow treats the result as fail-closed `BLOCKED` and still uploads the evidence artifact.

Synthetic evidence never claims more than was proven. If the trusted runner stopped before its normal safety result, primary/audit Git invariance fields are recorded as `unknown`; write-authority fields remain explicitly false.

## Security boundary

The fallback must not copy or publish unrestricted runner stderr/stdout. In particular it must never export:

- `runner.log`;
- `controller-execution.log`;
- source PDFs;
- source JSON;
- discovery captures;
- arbitrary exception text from retailer/source payloads.

The purpose is deterministic diagnosis of the control-plane failure class, not broader logging.

## RPi5 registration

The final merged runtime must be registered only from the retailer-dedicated clone:

```text
/home/andris/hermes-deals-audit-source-lidl
```

Use the exact squash-merge SHA of the final control-plane PR. Do not register the intermediate dedicated-clone SHA and then register this hardening SHA separately.

After registration, #224 may be rerun with the already-authorized observation inputs. Any synthetic `BLOCKED` result remains evidence of a control-plane problem and does not count as second-family Gate B evidence.
