# Phase 5G B15J5 — EDEKA description package normalizer shadow

B15J4 proved that four current EDEKA offers lacked package identity in normalizer-v1.1 even though their immutable `raw_payload.description` carried explicit first-party metric quantities.

Candidate normalizer-v1.2 adds a conservative EDEKA-only third fallback:

1. explicit `package_text_raw`;
2. first-party EDEKA image filename metric token;
3. top-level `raw_payload.description` explicit metric token.

The description fallback:

- strips parenthesized and trailing unit-price fragments such as `1 kg = ...`;
- accepts one unique metric signature or one unique multipack signature;
- rejects descriptions with multiple conflicting metric signatures;
- never runs for non-EDEKA offers;
- does not create identity rows or automatic write authority.

Expected target evidence:

- Cevapcici: EDEKA 600 g conflicts with ALDI Nord 800 g;
- Kulturheidelbeeren: EDEKA 500 g exactly matches ALDI Nord 500 g and becomes the only human-review canary candidate;
- Barilla Pasta: EDEKA 500 g conflicts with Lidl 1 kg;
- Hähnchenunterkeulen: EDEKA 1 kg conflicts with Lidl 1.5 kg.

This phase is a disposable-source and production-data shadow only. It does not modify main, production source, runtime, database, Compose, or systemd.
