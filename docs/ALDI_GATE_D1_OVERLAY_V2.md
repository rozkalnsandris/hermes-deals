# ALDI Gate D1 overlay V2

Issue: #250  
Failed V1 run: `31162330432`  
Frozen V1 registration: `690a0a09364b59e323230d24af006542bbdb1012`  
Frozen V1 bundle manifest SHA256: `481bd9ea014afb928f9f2b4b5d5f84c6f571c72c2524d7b442b16124ca73169f`

## Root cause

The repository Gate B replay plan is stored as a bounded chunk index plus eight Base64 fragments. SHA256 `3188821faa36a6d9fb598fde521a59993e6cb11678a8160e4afead4ba4fcfdd4` is the decoded/canonical Gate B plan identity, not the raw chunk-index JSON file SHA.

Gate D1 V1 incorrectly compared the raw transport file SHA to that decoded identity before invoking the already merged authoritative Gate D/Gate C loader. The first real RPi5 run therefore stopped before evidence discovery.

## Overlay design

V2 does not rewrite or mutate the frozen V1 registration. Instead it:

- requires the exact V1 commit and exact V1 bundle manifest SHA above;
- validates the real Gate B chunk transport through `load_gate_b_authoritative()`;
- requires the decoded/canonical Gate B identity `3188821f...`;
- delegates only the filesystem discovery pass to V1 with its raw precheck temporarily bound to the actual transport SHA;
- restores the public result identity to the decoded/canonical Gate B SHA;
- records both raw transport SHA and decoded identity in `gate_b_transport`.

## Failure evidence

V1 deleted staging stderr on failure, so run `31162330432` uploaded only the runner exit code. V2 exports no raw stderr. On failure it emits a bounded `discovery-failure.json` containing only:

- exception type;
- SHA256 of the exception message;
- `raw_exception_exported=false`;
- `raw_evidence_exported=false`;
- production and review-pack authorization false.

## Safety

Overlay V2 remains discovery-only. It performs no parser execution, candidate creation, production DB/Review write, approval/publication, deploy, scheduler/retry, canary or B15M2 V08 action. The strict ALDI 41/41 automatic-promotion gate is unchanged.

After squash merge, only the audit clone is synchronized to the exact overlay merge SHA. The overlay installer verifies the existing V1 bundle immutability and registers a separate dispatcher. The real V2 workflow run remains a separately owner-authorized step.
