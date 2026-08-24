# Kaufland K3C isolated import-stage remediation

Refs #773, #749, #702, #741, #770, #772, #769.

## Scope

This document records the source-only remediation after the second owner-authorized Kaufland K3C promo-structure diagnostic failed closed during the isolated Python import preflight. It does not authorize another diagnostic, host change, dependency installation, retained-evidence mutation, parser implementation, production write, or deploy.

## Immutable incident evidence

GitHub Actions run `32774900613` executed `Kaufland K3C promo structure RPi5 diagnostic` from exact `main=ab78367048626896f6b2f7e5d82bbaaa2972cb25`.

The hosted authorization job passed. It independently accepted:
- registration PR `#772`;
- registration SHA `ab78367048626896f6b2f7e5d82bbaaa2972cb25`;
- execution checkout SHA `ab78367048626896f6b2f7e5d82bbaaa2972cb25`;
- current-main witness at the same SHA;
- reviewed registration ancestry, CI proof, and trusted K3C source identity.

The fixed RPi dispatcher then returned:
- `BRIDGE_EXECUTION_STATUS=BLOCKED`;
- `REASON_CODE=DIAGNOSTIC_RUNTIME_IMPORT_FAILED`;
- `diagnostic_status=UNAVAILABLE`;
- dispatcher exit `30`;
- `promo_role_promoted=false`;
- no production deploy or diagnostic host mutation authorization.

Sanitized artifact:
- artifact ID `9537565466`;
- ZIP digest `sha256:574b1cf92cc65fe3f8c2f25bc94df5c4bd5066512b2555e987da22504eb07a8d`;
- only summary/manifest evidence was exported;
- `diagnostic_exit_code=null`.

The diagnostic module itself was not executed. The owner authorization used for run `32774900613` is consumed. No rerun, rerun-failed, cleanup, alternate runtime path, or dependency mutation is authorized by this remediation.

## What is proven and what is not

Proven:
- the source checkout/registration/hosted GitHub authorization boundary passed;
- the fixed RPi dispatcher reached the exact isolated import preflight;
- that preflight returned nonzero and failed closed before diagnostic execution;
- private import stderr did not enter the GitHub artifact;
- no public-promo role was promoted.

Not proven:
- which Python import failed;
- whether `bs4`, `httpx`, an internal Kaufland module, timezone data, or another transitive import is the root cause;
- whether any dependency is absent from another Python environment;
- whether changing interpreter or installing a package would be correct.

Do not infer a missing dependency from the bounded reason alone.

## Python documentation basis

The reviewed bridge intentionally uses `/usr/bin/python3` with `PYTHONNOUSERSITE=1`. Python documents that `PYTHONNOUSERSITE` prevents the user site-packages directory from being added to `sys.path`.

Python also documents that `ImportError` and `ModuleNotFoundError` carry structured import information, while `importlib.util.find_spec()` can import a parent package when the requested name is a dotted submodule. For this bridge, the safer evidence boundary is therefore to execute the real fixed imports under the exact reviewed runtime and export only fixed stage tokens — never exception messages, traceback, paths, or dynamically supplied module names.

## Source remediation contract

The dispatcher keeps the exact existing runtime identity:
- unprivileged user `andris`;
- `/usr/bin/env -i`;
- fixed `HOME`, `USER`, `LOGNAME`, PATH and `LANG`;
- `/usr/bin/python3`;
- backend working directory `/home/andris/hermes-deals/backend`;
- `PYTHONDONTWRITEBYTECODE=1`;
- `PYTHONNOUSERSITE=1`;
- `PYTHONHASHSEED=0`.

Before retained evidence can be read, it performs actual fixed imports in this order:
1. `bs4` -> `DIAGNOSTIC_IMPORT_BS4_FAILED`;
2. `httpx` -> `DIAGNOSTIC_IMPORT_HTTPX_FAILED`;
3. `app.kaufland_source_card_contract` -> `DIAGNOSTIC_IMPORT_SOURCE_CARD_CONTRACT_FAILED`;
4. `app.kaufland_source_discovery` -> `DIAGNOSTIC_IMPORT_SOURCE_DISCOVERY_FAILED`;
5. `app.kaufland_evidence_preflight` -> `DIAGNOSTIC_IMPORT_EVIDENCE_PREFLIGHT_FAILED`;
6. `app.kaufland_evidence_freeze` -> `DIAGNOSTIC_IMPORT_EVIDENCE_FREEZE_FAILED`;
7. `app.kaufland_real_k2_v2_derivation` -> `DIAGNOSTIC_IMPORT_K2_DERIVATION_FAILED`;
8. `app.kaufland_k3c_promo_structure_diagnostic` -> `DIAGNOSTIC_IMPORT_PROMO_MODULE_FAILED`.

A failed probe goes through the existing bridge `BLOCKED` summary path. Stderr remains in private staging and is not part of the export allowlist. The real diagnostic command remains unchanged and occurs only after all import probes pass.

These codes mean only that the fixed import stage failed. They do not mean that a named package is missing or prescribe an installation action.

## Semantic invariants

This remediation does not change:
- diagnostic structural logic;
- accepted `k-product-tile` owner boundary;
- public/reference/XTRA role semantics;
- `promo_role_promoted=false` policy;
- K2 retained bundle identity;
- validator payload schema;
- #702 parser implementation.

Public promo remains unproven until separately authorized, reviewed structural evidence supports a role under the existing precision-oriented acceptance rules.

## Validation and future gate

Source acceptance requires focused regression tests plus the repository's current CI/FAST-LANE Merge Gate. Merge remains explicit owner authority.

Because the K3C installer is a trusted control-plane anchor, a future merge of this remediation does not authorize live work. Before another diagnostic, fresh evidence must determine the required exact sequence, with separate owner authority for any RPi source sync, root registration, and one-shot diagnostic execution.

If any later authorized live mutation encounters error, ambiguity, or drift: preserve evidence and STOP. No automatic retry, rollback, cleanup, dependency installation, or alternate interpreter path.

**Production deploy: NO.**
