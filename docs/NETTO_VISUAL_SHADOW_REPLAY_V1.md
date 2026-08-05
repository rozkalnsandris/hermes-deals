# Netto visual shadow replay V1

Issues: #95, #27, #28

V1 imports the complete frozen first-pass visual corpus for family-primary Netto store `5659` and replays all 100 cells through the merged shadow-only visual-cell policy.

## Evidence binding

- 17 audited pages and 100 cells;
- campaigns `hz31_hasb_4` (26 cells) and `hz32_hasb` (74 cells);
- source archive SHA256 `882d61ad18ddca13680b97c0a27adf1a1db7874cabe337b61fc3ebc9b9d329f2`;
- N9 fixture manifest SHA256 `2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147`;
- 32 confirmed title defects, 4 price defects, 10 mixed-boundary cases and 2 out-of-scope cells.

The JSON fixture is losslessly gzip/base64 encoded. Both compressed and decoded SHA256 values are checked before parsing. Each row retains campaign, page and card identity; campaign bindings retain manifest/PDF SHA and parser identity.

## Replay contract

The replay passes only original candidate values and explicit scope/conflict signals to `netto_visual_cell_policy.py`. First-pass expected titles and prices remain review metadata and are never fed back as parser candidates.

The deterministic partition is:

- `automatic_candidate`: 65;
- `review_required`: 33;
- `excluded`: 2.

Every mixed boundary fails closed. Visual indexes 55 and 78 are excluded by scope. A different partition is a hard failure.

## Safety

- second review remains `pending`;
- `promotion_ready=false`;
- no production parser integration or source acquisition;
- no immutable evidence mutation;
- no database or Review write;
- no approval, publication, deployment, scheduler or production apply;
- brand, package and validity promotion remain blocked.

This PR does not close #95, #27 or #28.
