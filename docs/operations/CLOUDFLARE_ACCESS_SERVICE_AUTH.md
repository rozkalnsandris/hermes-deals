# Cloudflare Access service authentication for automated deploy checks

This runbook documents how Hermes Deals verifies its public production endpoints from GitHub Actions while the site remains protected by Cloudflare Access.

## When to use this pattern

Use a Cloudflare Access Service Token when an automated system such as GitHub Actions, a deployment runner, a monitoring bot or another non-interactive service must reach a hostname protected by Cloudflare Access.

Do not make the whole application public merely to let CI reach it. Hermes Deals includes Review endpoints that can modify production data, so the Access boundary must remain in place unless the application gains its own complete authorization layer.

## Architecture

The components have separate responsibilities:

- **Cloudflare Tunnel** carries traffic from Cloudflare to the private RPi5 origin. A Tunnel can serve either a public or an Access-protected hostname.
- **Cloudflare Access** decides who or what may reach the hostname. Without a valid browser session or service credential, Access returns its sign-in page instead of forwarding the request to Hermes Deals.
- **GitHub Actions** runs the serial post-merge deployment workflow and performs strict public API/UI contract checks.
- **Cloudflare Service Token** authenticates the non-interactive GitHub Actions request through Access.

## Failure signature

A successful local deployment can still finish with a red Action when the public check is intercepted by Access.

Typical evidence:

- the root deployment helper reports `DEPLOY_RESULT=PASS`;
- the local origin health URL returns valid Hermes Deals JSON;
- the public `/api/health` request returns HTTP `200` but the content type is `text/html`;
- the response body contains `Sign in · Cloudflare Access`;
- response headers identify the Access application, for example `CF-Access-Domain`;
- repeated requests do not recover, because this is an authentication failure rather than temporary edge propagation.

This means **Cloudflare Access**, not Cloudflare Tunnel and not the Hermes Deals API, intercepted the request.

## Cloudflare setup

### 1. Create a Service Token

In Cloudflare Zero Trust:

1. Open **Access controls → Service credentials → Service Tokens**.
2. Create a token with a descriptive name such as `hermes-deals-github-actions`.
3. Copy the generated **Client ID** and **Client Secret** immediately.
4. Store neither value in the repository, an issue, a pull request, a terminal transcript or a deployment artifact.

Cloudflare shows the Client Secret only when it is created or rotated.

### 2. Attach a Service Auth policy

Open the Access application for the protected hostname and create or attach a policy with:

- **Action:** `Service Auth`
- **Include selector:** `Service Token`
- **Value:** the Service Token created for the automation

Keep the normal browser/family access policy in place. The Service Auth policy adds non-interactive access for the token; it does not make the hostname public.

For Hermes Deals, the Access application protects `deals.rozkalns.net`.

## GitHub repository secrets

In the repository, open:

**Settings → Secrets and variables → Actions → Repository secrets**

Create exactly these secrets:

- `CF_ACCESS_CLIENT_ID` — value is only the raw Cloudflare Client ID
- `CF_ACCESS_CLIENT_SECRET` — value is only the raw Cloudflare Client Secret

Do not include header names, colons, quotes or labels in the secret values.

Correct conceptual form:

```text
CF_ACCESS_CLIENT_ID=<raw client ID>
CF_ACCESS_CLIENT_SECRET=<raw client secret>
```

Never commit the actual values shown above.

## Request headers

Every automated request passing through Access must include:

```text
CF-Access-Client-Id: <client ID>
CF-Access-Client-Secret: <client secret>
```

Hermes Deals reads the values only from GitHub Actions secrets and sends them as request headers for:

- `/api/health`
- `/ui`
- `/ui/review`

The workflow fails before making a public request when either secret is missing or empty. It also rejects newline characters to prevent malformed header injection.

## Secret-handling rules

The workflow must never:

- print either credential;
- write either credential to the evidence directory;
- include either credential in JSON reports;
- persist request headers containing credentials;
- accept credentials from repository files or pull-request input;
- weaken the public API/UI checks merely because Access authentication is enabled.

The deployment evidence may record only a non-sensitive boolean such as:

```json
{
  "cloudflare_access_service_auth": true
}
```

Response headers from the origin may be saved, but request headers containing the token must not be saved.

## Verification after setup

After merging a workflow change:

1. Confirm the `Hermes Deals CI` push run on `main` succeeds.
2. Confirm `Deploy merged main to production` starts automatically through `workflow_run`, not by manual `workflow_dispatch`.
3. Confirm the RPi5 deploy helper reports the intended production SHA and `DEPLOY_RESULT=PASS` or a safe no-op result.
4. Confirm the public verification step reports:
   - `PUBLIC_API_HEALTH=PASS`
   - `PUBLIC_UI_BUNDLE=PASS`
   - `PUBLIC_REVIEW=PASS`
   - `PUBLIC_CLOUDFLARE_ACCESS=PASS`
5. Inspect the uploaded deploy evidence:
   - `/api/health` is `application/json` and identifies `hermes-deals-api`;
   - `/ui` and `/ui/review` are `text/html`;
   - strict UI bundle markers are present;
   - forbidden external asset dependencies are absent;
   - no credential value appears anywhere in the artifact.
6. Confirm the production SHA equals the merged `main` SHA.

A green browser page alone is not sufficient evidence because a browser may already have a valid `CF_Session` cookie.

## Troubleshooting

### Still receiving the Access sign-in page

Check all of the following:

- the Service Auth policy belongs to the correct Access application;
- the policy action is `Service Auth`, not `Allow`;
- the include rule selects the intended Service Token;
- both GitHub repository secrets exist with exact names;
- secret values contain only the raw ID/secret, without header labels;
- the token was not rotated after the GitHub secrets were saved;
- the workflow sends both Access headers on every request.

### HTTP 401 or 403

Likely causes:

- invalid, expired or rotated credentials;
- Service Token not included by a matching Service Auth policy;
- policy attached to a different hostname/application;
- Access policy ordering or application path mismatch.

### HTTP 200 with JSON but strict UI checks fail

Access authentication is working. Investigate the actual deployment/UI contract rather than Cloudflare. Review the per-attempt evidence and required/forbidden UI markers.

### Local origin passes but public request cannot connect

Investigate Tunnel routing, DNS, Cloudflare edge health and origin reachability. This differs from the Access sign-in HTML signature.

## Rotation procedure

Rotate the token when credentials may be exposed, when required by policy, or during planned credential maintenance:

1. Rotate the Service Token in Cloudflare.
2. Immediately replace both GitHub repository secrets with the newly displayed values.
3. Do not delete the Service Auth policy unless the replacement token is also selected by the policy.
4. Run or trigger a controlled verification after the secrets are updated.
5. Confirm the public contract passes and no secret appears in logs or artifacts.

A rotated old secret stops authenticating. Coordinate rotation and GitHub secret replacement to avoid false-red deployments.

## Reuse for another project

For another protected service:

1. create a project-specific Service Token;
2. add a Service Auth policy only to that service's Access application;
3. store credentials as repository or environment secrets in that project's GitHub repository;
4. add the two Access headers only to the required automated requests;
5. preserve project-specific health and content validation;
6. document rotation ownership and evidence expectations.

Prefer one token per project or automation boundary. Do not reuse the Hermes Deals credentials across unrelated services.

## Hermes Deals incident history

- Issue #175 / PR #176: production UI bundle could deploy with broken external asset references; added self-contained production UI and strict public verification.
- Issue #177 / PR #178: added bounded retries and per-attempt evidence for temporary edge propagation.
- Issue #179 / PR #180: proved the persistent `text/html` response was Cloudflare Access and authenticated the checks with Service Token headers.
- Issue #181: added this reusable operational runbook.

The final verified pattern keeps Hermes Deals private behind Cloudflare Access while preserving automatic post-merge deployment and external production verification.
