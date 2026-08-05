# Cloudflare ingress target RPi5 audit

This audit verifies the current Hermes Deals Cloudflare Tunnel mapping without
uploading the cloudflared configuration, container metadata, runtime arguments,
environment variables, mounts, credentials or raw logs.

The fixed expected route is:

```text
deals.rozkalns.net -> http://192.168.0.180:9128
```

The audit belongs to issue #110 and is one evidence slice of issue #44.
This audit does not change Cloudflare, restart cloudflared, deploy Hermes Deals or access the
production database.

## What the collector checks

The root-owned collector locates one cloudflared runtime and evaluates only
allowlisted evidence sources:

- `/etc/cloudflared/config.yml` or `/etc/cloudflared/config.yaml` when mounted;
- explicit `--url`/`--hostname` runtime metadata;
- `TUNNEL_ORIGIN_URL`, `TUNNEL_URL` and `TUNNEL_HOSTNAME` metadata;
- bounded cloudflared configuration-update logs reduced in memory to normalized
  ingress fields.

The report never contains arbitrary observed hostnames or complete service URLs.
A mismatch is represented only as:

- expected protocol match;
- expected host match;
- expected port match;
- root-path match;
- normalized protocol enum;
- normalized host class;
- bounded observed port;
- normalized service kind.

The collector also verifies that local TCP port `9128` is listening and performs
one five-second `/api/health` request to `192.168.0.180:9128` with Host header
`deals.rozkalns.net`. The response body is discarded after a bounded content-type
classification.

## Result meanings

- `pass`: one running cloudflared runtime, an exact hostname-to-service mapping,
  local listener present and `/api/health` returned HTTP 200.
- `fail`: authoritative configuration proves a wrong/multiple mapping, the
  cloudflared runtime is not running, the origin listener is absent, or the
  local health endpoint returns a non-200 response.
- `partial`: cloudflared or its configuration cannot be proved safely, or a
  single-origin URL is present without a hostname binding.

A partial result must not be interpreted as a correct ingress mapping.

## One-time installation

Installation is a separate owner-authorized RPi5 action. Run only after the
implementation PR is squash-merged and exact-main CI is green.

Use a clean detached worktree that is not `/home/andris/hermes-deals`:

```bash
PRIMARY=/home/andris/hermes-deals
WORKTREE=/home/andris/hermes-deals-worktrees/cloudflare-ingress-audit

git -C "$PRIMARY" fetch origin main
SHA="$(git -C "$PRIMARY" rev-parse refs/remotes/origin/main)"
git -C "$PRIMARY" worktree add --detach "$WORKTREE" "$SHA"

sudo "$WORKTREE/tools/runner/install-cloudflare-ingress-audit.sh" \
  "$WORKTREE" "$SHA"
```

Expected installation markers include:

```text
INSTALLED=cloudflare-ingress
EXPECTED_HOSTNAME=deals.rozkalns.net
EXPECTED_SERVICE=http://192.168.0.180:9128
PRODUCTION_DEPLOYMENT=false
PRODUCTION_DATABASE_READ=false
PRODUCTION_DATABASE_WRITE=false
CLOUDFLARE_CONFIGURATION_MUTATION=false
WORKFLOW_EXECUTED=false
```

Installation creates:

- `/usr/local/libexec/hermes-deals-audits/cloudflare-ingress-audit.py`;
- `/usr/local/sbin/hermes-deals-cloudflare-ingress-audit-dispatch`;
- `/etc/hermes-deals-audits.d/cloudflare-ingress.conf`;
- `/etc/sudoers.d/hermes-deals-cloudflare-ingress-audit`.

The sudo rule grants `github-runner` only the fixed dispatcher command.

## Workflow execution

Execution is another separate owner authorization.

In GitHub Actions choose **Hermes Deals Cloudflare ingress RPi5 audit** and enter
the merged PR number that registered the installed audit. The workflow:

1. verifies the immutable owner login and numeric sender ID;
2. accepts only a PR squash-merged into `main`;
3. verifies that the merge SHA is reachable from current `main`;
4. performs no checkout on the self-hosted runner;
5. invokes only the registered root-owned dispatcher;
6. uploads exactly:
   - `ingress-audit.json`;
   - `dispatcher-manifest.json`;
   - `audit-exit-code.txt`;
7. comments the workflow result and artifact name on the registering PR.

The implementation PR itself does not install or execute the workflow.

## Evidence limitations

The audit intentionally cannot prove a remotely managed ingress rule when the
active cloudflared runtime exposes neither a local ingress file, an explicit
hostname URL pair, nor a bounded configuration-update record. That case returns
`partial` rather than guessing.

The artifact excludes:

- Cloudflare Tunnel tokens and credentials;
- full cloudflared command lines and environment;
- container names, IDs and images;
- Docker labels and mounts;
- local file paths;
- raw ingress configuration;
- raw cloudflared logs;
- arbitrary observed hostnames or URLs;
- response bodies.

## Removal

Removal is also separately authorized:

```bash
sudo /home/andris/hermes-deals-worktrees/cloudflare-ingress-audit/tools/runner/install-cloudflare-ingress-audit.sh --remove
```

Run the removal command only from the reviewed, clean detached worktree that
matches the installed audit registration.

Removal does not delete GitHub workflow artifacts or historical PR comments.
