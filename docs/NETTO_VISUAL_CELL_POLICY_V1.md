# Netto visual cell policy V1

Issue: #95  
References: #27, #28

## Purpose

`tools/netto_visual_cell_policy.py` is a shadow-only policy layer for one
visually segmented Netto offer cell. It converts explicit title, price, scope,
boundary and provenance signals into a deterministic candidate/Review/excluded
decision.

The module does **not** parse a PDF, infer a corrected product title, mutate the
N9 fixtures or connect to production. It is intended to sit between a future
visual cell extractor and the existing independent field promotion gate.

## Immutable regression basis

The adversarial fixture is bound to the family-primary Netto store:

- store external ID: `5659`
- scope: `family_primary_netto`
- source archive SHA256:
  `882d61ad18ddca13680b97c0a27adf1a1db7874cabe337b61fc3ebc9b9d329f2`
- N9 fixture manifest SHA256:
  `2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147`
- campaigns: `hz31_hasb_4` and `hz32_hasb`
- frozen cases: 32 title defects, 4 price defects and 10 mixed-boundary cases

Every case retains the exact campaign, page, card, manifest SHA, PDF SHA and
parser identity. The visual truth labels exist only in the fixture; the policy
module contains no product or campaign override table.

## Title policy

A title is blocked and routed to Review when any of these conditions apply:

- the candidate is missing;
- it is a known promotional/footer label rather than a product title;
- it is visibly truncated or marked incomplete;
- title ownership conflicts with the card;
- the cell contains mixed boundaries or multiple offer markers.

The policy never manufactures a replacement title. A clean title may become an
`automatic_candidate`, but this is only a shadow candidate and not a promotion
decision.

## Price policy

Normal and member prices are independent evidence types.

- exactly one normal price may be selected;
- exactly one member price may be retained separately;
- a member price can never replace a missing normal price;
- multiple distinct normal prices are ambiguous;
- any boundary or card-ownership conflict blocks normal-price selection.

This covers the confirmed Netto-Plus case where `3.99` is the normal red offer
price and `3.79` is the purple member price, without encoding that product or
campaign in the policy.

## Scope and field routes

The overall route is one of:

- `automatic_candidate`
- `review_required`
- `excluded`

`brand`, `package` and `validity` remain `review_required` in V1. The current
N9 schema has no independent brand or package prediction, and validity remains
bound to campaign-level evidence. `promotion_ready` is therefore always
`false`.

## Safety

V1 does not:

- enable automatic approval or publication;
- write to PostgreSQL;
- deploy or activate a scheduler;
- mutate immutable manifests, PDFs or N9 evidence;
- integrate with the production parser;
- close #95.

A later PR may wire this policy into an imported, reproducible visual parser
only after the parser source and a second review are present in GitHub.
