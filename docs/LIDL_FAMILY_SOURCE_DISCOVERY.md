# Lidl selected-store family-source discovery

Hermes Deals discovers the current and nearest future Lidl physical-store flyer
from the official selected-store hub for family store `DE06664`, Husener Straße
44, Dortmund.

## Binding contract

The last verified region is used only to recreate the selected-store cookie
context. Every flyer consumes the `/ar/<region>` encoded in its own official
hub link. A future flyer must never inherit the current flyer region.

The discovery step validates:

- the calendar day in `Europe/Berlin`, independent of the container's UTC clock;
- an HTTPX client with `trust_env=False`, so proxy and CA environment variables are not inherited;
- exactly one current flyer for the Berlin-local date;
- at most one nearest future flyer;
- Lidl-hosted hub and viewer URLs over HTTPS;
- route region advertised by the Schwarz flyer response;
- hub and API validity equality;
- HTTPS document URL and PDF magic bytes;
- exact SHA256 for raw JSON and PDF bytes.

## Write boundary

Discovery writes evidence only to an explicitly supplied empty output
directory. It does not write to the immutable corpus, the production database,
the Review Queue, or systemd.

Corpus archive, scan, profile validation, Review bridge planning, guarded
Review seeding, preview rendering, and timer installation are later explicit
gates.

The module uses atomic same-directory temporary files and `os.replace()` for
its evidence output. Existing evidence directories are never overwritten.

## Upstream replacement observation

Lidl may replace the public viewer/PDF for an already-active period. Discovery
records the newly advertised immutable identity. A historical corpus source is
never overwritten. The release canary treats a pre-recorded current-period
replacement as an explicit observation while the guarded next-period one-shot
continues only when its PDF and stable identity match the immutable corpus.
