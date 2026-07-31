# Persistent Hermes Deals UI development environment

Port roles:

- `192.168.0.180:9128` — immutable production;
- `192.168.0.180:9190` — persistent UI development and shared preview;
- `913x` — temporary immutable canary environments.

The `9190` environment is based on the currently deployed production API
image, not on the moving `main` branch. UI work is reconciled into a dedicated
integration worktree before the environment starts.

Architecture:

```text
browser :9190
  -> dedicated development Nginx
  -> dedicated development API from the deployed production image
  -> production PostgreSQL through forced read-only transactions
```

Safety controls:

- production `main` is read-only to this workflow;
- dedicated integration branch and worktree;
- V4 paths must not overlap production changes since the UI release base;
- separate Compose project and service names;
- production Docker network is referenced as external;
- API and Nginx root filesystems are read-only;
- Nginx runs as the image's unprivileged `nginx` user with all capabilities dropped;
- UI, config, and raw-data mounts are read-only;
- PostgreSQL has `default_transaction_read_only=on`;
- production port `9128` and containers remain unchanged;
- runtime secrets remain outside Git in a mode-600 file.

Control:

```bash
hermes-deals-ui-dev start
hermes-deals-ui-dev status
hermes-deals-ui-dev check
hermes-deals-ui-dev logs
hermes-deals-ui-dev restart
hermes-deals-ui-dev stop
```

Open:

```text
http://192.168.0.180:9190/
http://192.168.0.180:9190/ui
http://192.168.0.180:9190/ui/review
```

Review write actions fail closed because the development database connection
is forced read-only.
