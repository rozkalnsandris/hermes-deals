# Hermes Deals public-edge and local-origin diagnostic probe

This tool supports the read-only evidence collection required by issues #44 and #86. It compares the same bounded Hermes Deals API requests through:

1. the public Cloudflare URL;
2. a separately supplied local nginx/origin URL.

It does **not** restart services, change Cloudflare, deploy code, write to PostgreSQL, approve Review rows or alter production configuration.

## Probed endpoints

For one explicit `as_of` date, the tool performs exactly one request per target to:

- `/api/health`;
- `/api/v1/ui/overview?as_of=YYYY-MM-DD`;
- `/api/v1/deals/current?as_of=YYYY-MM-DD&view=current&limit=1&offset=0`.

There is no automatic retry loop.

## Example

Run from a trusted host that can reach both paths:

```bash
python tools/hermes_deals_origin_probe.py \
  --public-base-url https://deals.rozkalns.net \
  --origin-base-url http://192.168.0.180:9128 \
  --origin-host deals.rozkalns.net \
  --as-of 2026-08-05 \
  --timeout 5 \
  --pretty \
  --output /tmp/hermes-deals-origin-probe.json
```

`--origin-host` is optional. Use it when local nginx routing depends on the public host name.

The base URLs must use `http` or `https`, contain no embedded credentials and contain no query or fragment. The tool never accepts cookies, bearer tokens or arbitrary request headers.

## Sanitized evidence contract

The JSON report contains:

- schema version and UTC capture timestamp;
- the explicit `as_of` date;
- aggregate classification and severity;
- target, endpoint, URL, status and elapsed milliseconds;
- transport error category when no HTTP response exists;
- only these response headers:
  - `CF-Ray`;
  - `Retry-After`;
  - `Server`;
  - `Content-Type`;
  - `CF-Cache-Status`;
- only these structured problem fields:
  - `status`;
  - `error_code`;
  - `error_name`;
  - `ray_id`;
  - `retryable`;
  - `retry_after`.

Arbitrary HTML, plain-text error bodies, cookies, authorization data, internal traces and unknown JSON fields are discarded.

## Classifications and exit codes

| Classification | Meaning | Exit |
|---|---|---:|
| `healthy` | Both public and origin paths succeeded for every endpoint. | `0` |
| `edge_or_tunnel_failure` | Public requests failed with transport/502/503/504 behavior while the matching local origin requests succeeded. | `2` |
| `public_path_failure` | Only the public path failed, but not with the known edge/tunnel failure pattern. | `1` |
| `origin_or_application_failure` | Matching public and local-origin requests both failed. | `2` |
| `local_origin_probe_failure` | Public requests succeeded but the separately supplied local probe path failed. | `1` |
| `mixed_failure` | A remaining mixed degraded pattern. | `1` |

A classification narrows the failing hop; it is not by itself proof of the final root cause. Correlate the report timestamp and `CF-Ray` with sanitized `cloudflared`, nginx, API, PostgreSQL and host resource evidence before changing production.

## Safety and follow-up

- Running the probe authorizes observation only.
- A non-zero exit code does not authorize restart, deploy, rollback, tunnel changes or database action.
- Keep generated reports free of surrounding shell environment dumps.
- Attach only reviewed, sanitized evidence to GitHub.
- Any production configuration or runtime change requires a separate explicit owner authorization.
