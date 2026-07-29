# Lidl V6.3.1 parser provenance bundle

This directory preserves the exact parser source identity that generated the
authoritative KW31 `scan-0005` and KW32 `scan-0003` corpus observations.

It is provenance evidence, not a production runtime parser.

Rules:

- `r61_base.py` is frozen.
- `r61_shadow.py` is exact V6.3.1 source.
- historical corpus parser rows are immutable.
- do not micro-tune this copy to close the four known KW32 omissions.
- future automatic rescans require an explicit migration of the executable
  corpus workflow into the main repository.
- the former `/home/andris/hermes-deals-codex` worktree is evidence only and
  is not an authoritative source after this bundle is committed.
- `r61_shadow.py` and its exact historical test intentionally keep their
  original byte-for-byte EOF whitespace. The local `.gitattributes` disables
  Git whitespace diagnostics only for those two provenance files; their exact
  SHA256 gates remain mandatory.

The four known KW32 omissions belong to a separate reviewed completeness-rescue
layer.
