# Netto RPi5 shadow audit security boundary v1

The GitHub-hosted authorization job never checks out pull-request code. It runs
from the default branch, accepts only the exact `audit:netto-shadow-v1` label,
requires the repository owner's login and numeric GitHub identity, and accepts
only a PR already merged into this repository's `main` branch.

The self-hosted job can invoke only
`/usr/local/sbin/hermes-deals-netto-shadow-audit-dispatch` through its dedicated
sudo rule. The dispatcher requires the exact registered commit and verifies the
root-owned runner/tool SHA-256 values before executing the audit as the
unprivileged `andris` user.

The `github-runner` account must not be in the Docker group. The audit does not
receive repository credentials, database credentials or a production-write
authorization.
