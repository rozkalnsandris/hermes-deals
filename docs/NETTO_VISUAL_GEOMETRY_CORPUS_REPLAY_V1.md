# Netto visual geometry corpus replay V1

Issue: #95

## Goal

Replay the merged vector-first Netto shadow parser against the exact N9/N10 17-page / 100-cell visual evidence without using reviewed titles or prices to locate a card.

The bridge is intentionally evidence-only. It does not activate a production parser or make any promotion decision.

## Frozen inputs

- family-primary Netto store: `5659`;
- source archive SHA256: `882d61ad18ddca13680b97c0a27adf1a1db7874cabe337b61fc3ebc9b9d329f2`;
- N9 `fixture-manifest.json` SHA256: `2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147`;
- N10 raw ledger SHA256: `bf35bff323d76a2b29a7248df067641e5b9f2a7d29329cf53bf9fc0ae832734a`, exactly `104385` bytes;
- `hz31_hasb_4` PDF SHA256: `9e878399868bd3ff5422954e7547ea68cfd2a518209ed01c96940a0eafb258ca`, 76 pages;
- `hz32_hasb` PDF SHA256: `f87bb55bc735ecd7fbbf0735ad848615b30a543639a94265464d1c57e621cb36`, 49 pages;
- geometry parser identity: `netto-visual-geometry-shadow-v3-unrotated-page-space`.

The N9 manifest is the card-location authority. Each cell already contains the stable `cell_id`, campaign/page identity and normalized `region_x0/y0/x1/y1` boundaries inherited from N8 v2.

N10 is only the post-binding comparison truth. Its expected title and price are never used to choose a geometry group.

## Mapping contract

For each of the 17 N9 fixture pages:

1. load the exact campaign PDF and run the merged PyMuPDF geometry parser for the whole page;
2. convert the N9 normalized cell boundary to points using the parser's unrotated `width_points` / `height_points`;
3. collect geometry groups whose bbox center is contained by the N9 cell;
4. keep bbox intersection only as diagnostic evidence;
5. bind automatically only when exactly one group center belongs to the cell;
6. if there are zero or multiple center groups, fail the cell closed to Review;
7. if one geometry group is provisionally bound to multiple N9 cells on the same page, fail all involved cells closed as a cross-cell reuse;
8. only after a unique geometry binding exists, compare selected title and selected normal price with the N10 reviewed truth.

Title comparison records both exact and normalized equality. Price comparison uses exact two-decimal `Decimal` values. No comparison result changes the `promotion_ready=false` safety boundary.

## PyMuPDF documentation basis

The implementation follows the current PyMuPDF geometry contract for the repository-pinned `PyMuPDF==1.28.0`:

- `Rect.contains()` checks point or rectangle containment;
- `Rect.intersects()` checks non-empty overlap;
- page text clipping is not used as the primary card-binding method because `Page.get_text(..., clip=...)` omits characters whose bounding boxes are not fully contained by the clip;
- the merged parser already uses unrotated page dimensions (`Page.cropbox.width` / `height`) to match extracted text/vector coordinates.

This keeps card identity based on N9 geometry instead of title similarity or N10 expected values.

## Output safety

The result always records:

- `second_review_status=replay_evidence_only`;
- `review_only_default=true`;
- `promotion_ready=false`;
- automatic approval/publication disabled;
- no PostgreSQL write;
- no deployment;
- no production apply authorization.

The output path is create-only and an existing path is rejected.

## Intended controlled run

After this bridge is merged, run it in an isolated read-only RPi5 evidence context with the exact retained N9 manifest and immutable Netto corpus:

```bash
python3 tools/netto_visual_geometry_corpus_replay.py \
  --n9-manifest /path/to/netto-n9/generated/fixture-manifest.json \
  --corpus-root /home/andris/hermes-deals-netto-corpus/flyers \
  --n10-ledger backend/tests/fixtures/netto/n10_full_visual_review_v1.json \
  --output /private/audit/path/netto-geometry-corpus-replay.json
```

That real 100-cell result is the next evidence gate. It still does not by itself close #95: the acceptance criteria require review of the reproduced corrected cells before any promotion decision.
