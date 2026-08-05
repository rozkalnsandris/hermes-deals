# ALDI A3.0 V03 browser-backed frozen acquisition

## Evidence correction

The SHA-verified uploaded evidence does **not** show four independent live sources.
It shows four successful responses only because the two `preview` control pages were
requested with two header profiles each:

- `preview` page 1: `302` to signed `cdn.ipaper.io`, then `200 image/jpeg`,
  SHA256 `d0bfa8718f28b1f88a22991b00ea6999cc00517bbd8c8f51b050144307fa55da`;
- `preview` page 41: `302` to signed `cdn.ipaper.io`, then `200 image/jpeg`,
  SHA256 `61afc0b2a9e65ac68fd5a67c9ddf4a35fc393afa661de21d6030a6a38268acec`;
- `current` page 1 and page 49: `404 text/html`, 5,254 bytes, identical body
  SHA256 `0b4ee3b9aec6ab88bbae1bfdd3f04dec2f8e4573ab1642ca978aa81b6d57455a`
  with both header profiles.

Therefore headers are not the missing `current` fix. The frozen KW31 iPaper object
has expired or been removed, while the frozen KW32 preview object remains live.

## V03 behavior

V03 uses Chromium through Playwright, but preserves the original trust boundary:

1. verify the exact A2.1 archive and derive only its frozen source plan;
2. create one isolated browser context per source;
3. probe both frozen viewer surfaces;
4. retrieve every exact frozen page URL through the context-bound request client;
5. fall back to browser page navigation only for the same exact URL;
6. follow signed CDN redirects and save image bytes immediately;
7. redact bearer token/signature query values from stored evidence;
8. validate initial/final hosts, image magic, size, SHA256 and exact page numbers;
9. continue across both sources before deciding the result;
10. require exact `49 current + 41 preview` for PASS.

A missing source produces `BLOCKED`, not a false PASS. Successfully acquired pages
remain in immutable shadow evidence so a still-live source is not lost while another
source is expired.

## Runtime prerequisite

The runner never installs software. Supply:

- a trusted Chromium executable through `ALDI_A30_BROWSER_EXECUTABLE` or one of the
  standard system paths;
- a pre-provisioned Python containing Playwright through
  `ALDI_A30_BROWSER_PYTHON`.

This keeps dependency installation separate from evidence acquisition and avoids
mutating production during the audit.

## Run contract

Run from a clean isolated repository clone on `main` after merge:

```bash
REPO=/home/andris/hermes-deals-audit-source \
HERMES_AUDIT_EXPECTED_HEAD=<exact-merged-main-sha> \
ALDI_A30_BROWSER_PYTHON=<playwright-venv-python> \
ALDI_A30_BROWSER_EXECUTABLE=/usr/bin/chromium \
bash tools/run-hermes-deals-aldi-a30-browser-acquisition-v03.sh
```

Exit codes:

- `0`: all 90 frozen pages acquired and the existing A3.0 integrity gate passed;
- `3`: controlled blocker, with partial evidence preserved;
- `2` or another non-zero code: runtime/configuration error.

With the uploaded KW31/KW32 evidence, the expected honest result is currently:

- `current`: `expired_source`, 0/49;
- `preview`: eligible for live acquisition, up to 41/41;
- overall: `BLOCKED` until an authoritative exact-current recovery source is found.

## Safety

V03 does not write the database, collector source state, Review Queue, approvals,
publication state, Docker, systemd or production runtime. It does not switch, reset,
stash or clean the selected repository.
