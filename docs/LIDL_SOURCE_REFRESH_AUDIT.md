# Lidl same-PDF source-refresh audit

Issues: #345, #287, #24. Design basis: #230 / PR #235.

## Purpose

This audit handles the fail-closed `WAIT_SOURCE_REVIEW` state where the official Lidl PDF and stable flyer identity are unchanged but canonical parser-input identity has changed.

The concrete rev05 family is fixed to:

- family: `aktionsprospekt-03-08-2026-08-08-2026-b1cf3b--src-6da2135ea984`;
- PDF SHA-256: `6da2135ea984d1f79bdb311dfa0d8affd1d2f8d46c63a1bba25b202a30a5fb16`;
- stable-source identity SHA-256: `7486e32f837869b3dedc36b5a129c034129f653bf698df4ad55649510623ff17`;
- frozen raw SHA-256: `d1af2062f10f5fd25d4ac197fe74459bf0c313d7f5890f5d96c3db9572b7ddf1`;
- frozen parser-input identity: `8d63c989fd1897215f9556942aec16636ce7c0e5a8bb05b5a672693f58519c5a`.

## Read-only R1 contract

The fixed RPi5 dispatcher reads only the exact immutable rev05 sibling and fetches the current exact Schwarz source for the fixed flyer/region. It reuses the same canonical semantics as `lidl_weekly_staging.py`, with focused parity tests for:

- stable-source identity;
- canonical parser-input identity excluding only top-level `dateTime` and `warnings`;
- product-binding projection/digest/count;
- added/removed/title-changed binding summary.

The authoritative corpus is hashed before and after the audit and must be byte/metadata-identical. The primary Git worktree/index and protected B15M2 V08 state must also remain unchanged.

GitHub receives only:

- `source-refresh-summary.json`;
- `source-review-template.json`;
- `audit-manifest.json`.

Raw PDF/JSON, product IDs, product titles, bounding boxes and full source payloads are never copied into the GitHub artifact or issue comment.

## Review template

R1 deliberately emits:

```json
{
  "decision": "PENDING_OWNER_REVIEW",
  "scope": "authoritative_staging_scan_only"
}
```

with exact reference/live parser-input and product-binding hashes/counts plus the observed binding-change counts. The normal `_validate_source_review()` rejects this pending template. It becomes eligible for R2 staging only after a separate explicit owner approval changes `decision` to `approve_parser_input_refresh` and supplies approver, timestamp and note while preserving every exact identity and permission field.

R1 does not authorize that approval.

## GitHub command

After the exact merged runtime has received the one-time root trust bootstrap, the owner-only issue command on #345 is:

```text
/hermes-lidl-source-refresh-audit pr=<merged-runtime-pr> as_of=2026-08-08
```

The GitHub-hosted authorizer accepts only the allowlisted repository, owner login/numeric ID, issue #345, a full-match command, a PR already merged to `main` and reachable from current `main`, and a date inside the exact rev05 validity window.

The self-hosted job has no repository token permission and performs no checkout. It can only invoke `/usr/local/sbin/hermes-deals-lidl-source-refresh-audit-dispatch` through the dedicated sudoers rule.

## Safety boundary

R1 fixes all of these to false:

- corpus write;
- parser scan;
- production database write;
- Review write;
- approval/publication;
- production deploy;
- systemd/timer change;
- automatic retry;
- Gate C/D authorization.

R2 reviewed staging scan and any later R3 create-once corpus promotion are separate explicit boundaries.