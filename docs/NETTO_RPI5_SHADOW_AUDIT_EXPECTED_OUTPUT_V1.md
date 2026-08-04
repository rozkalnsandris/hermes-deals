# Netto RPi5 shadow audit expected output v1

The sanitized artifact must include `dispatcher-evidence-manifest.json` and may
include only the files listed by the dedicated dispatcher allowlist.

`audit-summary.json` must always report:

- the exact registered Git commit;
- `production_apply_authorized=false`;
- `database_write_performed=false`;
- `deployment_performed=false`;
- independent readiness values for issue #27 corpus evidence and issue #28 real
  transition evidence;
- `acceptance_status=blocked` until both evidence gates are proven.

A successful workflow run proves that the audit executed and the artifact was
sanitized. It does not by itself prove the two issue acceptance criteria.
