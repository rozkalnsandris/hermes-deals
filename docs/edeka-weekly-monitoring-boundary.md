# EDEKA unattended weekly monitoring boundary

## Purpose

Issue #26 has already proven two consecutive real EDEKA Patzer campaigns and the bounded production canary lifecycle (`verify -> apply -> replay -> rollback`). The remaining engineering gate is unattended source freshness/failure monitoring.

This source change deliberately stops before activation.

## Runtime contract

`tools/edeka_weekly_monitor_runtime.py` wraps the existing reviewed EDEKA shadow-cycle runner for the exact family market (`071897` / `587881`).

Each scheduled observation:

- requires a clean exact-SHA dedicated EDEKA audit checkout;
- runs the existing isolated shadow capture, never the production persistence path;
- validates exact Patzer source identity, isolated replay delta `0`, and all no-production-write safety flags;
- classifies an active campaign as `COMPLETE` / exit `0`;
- accepts an already-published near-future campaign as `COMPLETE` / exit `0`;
- classifies a campaign whose `valid_until` is before the local Europe/Berlin observation date as `STALE` / exit `20`;
- classifies source-runner failure, timeout or evidence-validation failure as `BLOCKED` / exit `30`;
- writes a create-only `monitor-receipt.json` with hashes of captured stdout/stderr rather than copying raw output into monitor evidence.

`STALE` and `BLOCKED` are deliberately non-zero so a later systemd activation can use bounded `Restart=on-failure` and `OnFailure` alerting.

## Non-activating systemd plan

`tools/edeka_weekly_monitor_activation_plan.py` generates, but does not install or execute:

- `hermes-edeka-weekly-monitor.service`;
- `hermes-edeka-weekly-monitor.timer`;
- `hermes-edeka-weekly-monitor-failure@.service`;
- `activation-plan.json`.

The schedule, retry delay/window/count and timeout remain explicit operator inputs. The plan runs `systemd-analyze calendar` and `systemd-analyze verify` before any later installation step, keeps the service as user `andris`, applies `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=read-only`, and makes only the EDEKA shadow evidence, monitor evidence and hash-locked runtime cache writable.

Activation, disable and rollback commands are represented only as data. Merge does not authorize `systemctl`, root installation, a live source refetch, production DB/Review/publication writes, or production deploy.

## Later authority boundary

After merge and exact-main CI, any root/unit registration remains a separate explicit owner authorization. Enabling/starting the timer remains another explicit owner authorization. A live scheduled observation necessarily performs an EDEKA source fetch, so activation must not be inferred from source merge.
