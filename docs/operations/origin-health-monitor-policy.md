# Hermes Deals origin health monitor policy

This repository-only tool evaluates a bounded rolling window of already sanitized
Hermes Deals public-edge/local-origin probe reports.

It supports issue #44 by separating:

- repeated public HTTP 5xx samples;
- public transport failures;
- edge/tunnel classifications;
- shared public-and-origin failures;
- local-origin probe failures;
- insufficient history.

The evaluator performs **no network requests**. It does not run the probe,
install a service, create a timer, restart containers, change Cloudflare, read
PostgreSQL or deploy Hermes Deals.

## Input contract

Each `--input` file must be a JSON report produced by
`tools/hermes_deals_origin_probe.py`.

The evaluator validates the complete sanitized contract before using a report:

- probe schema version `1`;
- canonical `as_of` date;
- timezone-aware UTC `captured_at`;
- one unique public and origin probe for each fixed endpoint:
  - `health`;
  - `overview`;
  - `deals`;
- the fixed public URL `https://deals.rozkalns.net`;
- the fixed local origin `http://192.168.0.180:9128`;
- exact probe fields and consistency between HTTP status, `ok` and transport
  error;
- the existing response-header and problem-field allowlists;
- reported classification and severity agree with the six probe results.

Unknown fields, unsafe response headers, raw problem details, malformed URLs,
duplicate timestamps and inconsistent classifications fail closed.

Each input file is limited to 1 MiB. At most 100 files are accepted.

## Rolling policy

Defaults:

| Setting | Default | Allowed |
|---|---:|---:|
| `window_size` | 5 | 3–20 |
| `min_samples` | 3 | 1–`window_size` |
| `alert_threshold` | 3 | 2–`window_size` |

Reports are sorted by their validated UTC capture timestamp. Only the latest
`window_size` reports are evaluated.

The threshold counts **samples**, not individual endpoints. A single report
with three public 502 responses counts as one public-5xx sample.

## States and exit codes

| State | Meaning | Alert | Exit |
|---|---|---:|---:|
| `healthy` | All evaluated samples are healthy. | false | `0` |
| `insufficient_data` | Fewer than `min_samples` valid reports exist. | false | `1` |
| `degraded_public` | Public failures exist below the alert threshold. | false | `1` |
| `degraded_local_origin` | Local-origin failures exist below the alert threshold. | false | `1` |
| `degraded_mixed` | Public and origin failures both occur in the window below the alert threshold. | false | `1` |
| `alert_public_5xx` | Public 5xx samples meet or exceed `alert_threshold`. | true | `2` |
| `alert_origin_or_application` | Shared public+origin failure samples meet or exceed `alert_threshold`. | true | `2` |
| invalid input | Any report or policy setting fails validation. | none | `3` |

Shared origin/application alerting takes priority over public-5xx alerting when
both thresholds are met, because the local origin is also failing.

Public transport failures are counted separately and do not become
`alert_public_5xx`; they remain degraded until a later activation layer defines
an independently reviewed transport-failure policy.

## Example

```bash
python tools/hermes_deals_origin_monitor.py \
  --input /safe/probes/probe-01.json \
  --input /safe/probes/probe-02.json \
  --input /safe/probes/probe-03.json \
  --input /safe/probes/probe-04.json \
  --input /safe/probes/probe-05.json \
  --window-size 5 \
  --min-samples 3 \
  --alert-threshold 3 \
  --pretty \
  --output /tmp/origin-monitor-summary.json
```

The output contains only:

- monitor schema version;
- fixed state and latest-classification enums;
- alert boolean;
- validated UTC window boundaries;
- policy values;
- aggregate counts;
- trailing consecutive counts.

It never copies probe URLs, Ray IDs, response headers, problem fields, raw
bodies, logs or arbitrary input strings into the summary.

## Activation boundary

Merging this tool does not activate monitoring.

A separate owner-authorized change is required before any of the following:

- installing it on the RPi5;
- scheduling it;
- retaining production probe history;
- sending notifications;
- changing alert thresholds;
- exposing Cloudflare Tunnel metrics;
- restarting or reconfiguring services.

An alert result authorizes investigation only. It does not authorize a deploy,
restart, rollback, Cloudflare change or database action.
