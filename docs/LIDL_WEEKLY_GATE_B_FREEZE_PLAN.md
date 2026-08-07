# Lidl weekly automation — Gate B freeze plan

Issue: #24

## Purpose

Gate A can return the observable state:

- result: `WAIT`;
- one-shot result: `WAIT_SOURCE`;
- reason: `exact_source_not_archived_in_immutable_corpus`;
- selected physical-store source: available and usable;
- corpus mutation: not authorized.

The Gate B planner validates retained private Gate A evidence and produces a deterministic content-bound plan for freezing that exact source later. It does not copy or create anything inside the immutable corpus.

The planner also supports an official Lidl source revision for an already-frozen logical flyer. Lidl may keep the same flyer identifier, official flyer ID, viewer path, validity window, advertised regions and page count while publishing a new document path and new PDF bytes. Such a revision must be retained beside the old immutable source; the old source is never overwritten.

## Accepted input

The planner accepts one retained Gate A run directory directly under:

```text
/home/andris/hermes-deals-lidl-gate-a-evidence
```

The run must contain the original private evidence retained by the Gate A runner:

```text
run-request.txt
controller/controller-manifest.json
controller/one-shot/one-shot-status.json
controller/one-shot/discovery/discovery.json
controller/one-shot/discovery/family-<target>/meta.json
controller/one-shot/discovery/family-<target>/source.pdf
controller/one-shot/discovery/family-<target>/source.json
```

The sanitized GitHub artifact alone is intentionally insufficient because it does not contain the source bytes.

## Fail-closed validation

The planner requires all of the following:

- the run directory is a direct, non-symlink child of the authoritative Gate A evidence root;
- the request is exact-SHA bound and has every production, DB, Review, publication, deploy, timer and retry authority disabled;
- `use_previous=false` and `previous_manifest=none`;
- controller state is exactly `WAIT / one_shot_wait_source`;
- one-shot state is exactly `WAIT_SOURCE / exact_source_not_archived_in_immutable_corpus`;
- source readiness is `SOURCE_AVAILABLE`;
- target and Berlin date agree across request, controller, one-shot and discovery evidence;
- PDF and raw JSON byte counts and SHA-256 values agree across all evidence;
- official flyer ID, validity window, advertised regions and page count agree with the stable source identity derived from `source.json`;
- the proposed flyer key is path-safe;
- the authoritative corpus root and all inspected corpus children are non-symlink directories/files;
- no corpus flyer already contains the same PDF identity or the same full stable source identity.

Any mismatch blocks the plan.

## Destination strategy

For the first immutable source of a flyer, the destination remains the canonical flyer identifier:

```text
flyers/<flyer-key>/
```

If that base directory already exists, the planner permits a new source revision only when the existing base source and the live source have the same logical identity after removing only `document_path`, and the two `document_path` values are different. The logical identity therefore still binds:

- official flyer ID;
- viewer path;
- validity start/end;
- advertised regions;
- page count.

A validated revision receives a deterministic content-addressed sibling:

```text
flyers/<flyer-key>--src-<first-12-hex-of-pdf-sha256>/
```

The revision path must not already exist. An unrelated flyer occupying the base key, an unsafe or incomplete base source, an unchanged document path, an exact PDF duplicate, a full stable-identity duplicate, or an occupied revision destination all fail closed.

This preserves every earlier immutable revision. Gate A is compatible with revision siblings because corpus matching is based on exact PDF SHA-256 followed by stable-source-identity verification, not on the directory name.

## Output

A successful plan returns:

```text
result=READY_TO_FREEZE
reason=validated_gate_a_wait_source_evidence
```

The JSON includes:

- the exact Gate A commit, image ID, target and Berlin date;
- the logical source flyer key, validity window, region, page count and official ID;
- PDF, raw JSON and stable source identity SHA-256 values;
- the exact proposed corpus destination and source/destination file map;
- `destination.strategy`, either `base_flyer_key` or `content_addressed_source_revision`;
- the base flyer key and, for revisions, the prior/live document paths;
- a deterministic plan fingerprint bound to the destination strategy;
- an exclusive-create apply contract;
- explicit `separate_owner_authorization_required=true`.

Repeated planning over unchanged evidence produces byte-identical JSON.

## Usage

```bash
python tools/lidl_gate_b_freeze_plan.py \
  --gate-a-run-dir \
    /home/andris/hermes-deals-lidl-gate-a-evidence/lidl-gate-a-<run> \
  --output /home/andris/lidl-gate-b-freeze-plan.json
```

The command is read-only with respect to the immutable corpus. The output path must not already exist.

## Safety boundary

Every plan fixes:

```text
plan_only=true
corpus_write_authorized=false
database_write_authorized=false
review_write_authorized=false
production_publish_authorized=false
production_deploy_authorized=false
systemd_change_authorized=false
bounded_retry_authorized=false
```

This change does not:

- copy source files into the corpus;
- replace or modify an existing immutable flyer revision;
- create a scan;
- run the parser;
- seed or approve Review rows;
- write to PostgreSQL;
- publish offers;
- deploy production;
- install or activate a timer;
- authorize Gate C or Gate D.

A separate owner-authorized Gate B apply step must consume one reviewed exact plan, use private staging plus exclusive destination creation, verify every copied SHA-256, and fail closed without touching an existing corpus family or revision.
