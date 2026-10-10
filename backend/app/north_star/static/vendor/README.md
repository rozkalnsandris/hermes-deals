# HTMX 2.0.11

Self-hosted upstream distribution, unchanged, shared version/pin with Deals PR #953.

- Repository: https://github.com/bigskysoftware/htmx
- Commit: `fa978b24e75fb03c137bf2cdae4fef0e711cf8a1`
- Source: `dist/htmx.min.js`
- Git blob: `e6b8394acb5cda3281a68b4078775ec348d8eafc`
- License: adjacent `HTMX-LICENSE`, copied from the same commit.

The existing Docker `COPY app ./app` includes these bytes in the immutable release;
no CDN or network download is required at build time or in the browser. The
household UI disables evaluation, response scripts and history snapshots.
