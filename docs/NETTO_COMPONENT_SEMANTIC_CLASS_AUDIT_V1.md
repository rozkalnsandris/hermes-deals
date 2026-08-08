# Netto component semantic-class audit v1

This diagnostic consumes the frozen output of `netto_object_component_signature_audit_v1` and groups cells into exact semantic classes using only per-component node composition and source-derived boolean structure.

Independent ownership truth is removed before class construction. The class set and its SHA-256 are frozen first; only then are the existing 88 single-source / 10 mixed-source / 2 excluded-control labels used to report class purity and collisions.

The audit is intentionally non-promotable. It does not fit a classifier, change parser behavior, retain image binary payloads, use OCR, write DB/Review state, approve/publish offers, deploy production, or alter systemd/Cloudflare. A mixed-only class in this audit would be evidence for another separately reviewed diagnostic, not permission to change routing.
