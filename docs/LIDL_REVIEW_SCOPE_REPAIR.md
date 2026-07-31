# Lidl Review scope repair — B15I1

## Target policy

Hermes Deals Lidl production includes only:

- food;
- drinks;
- household consumables.

Flowers and plants, personal-care products, clothing, electronics, tools,
furniture, camping equipment and other durable non-food are excluded.

## Incident

The B15H6 filtered Review seed treated every physical-store row with
`scope=review` and fixed pricing as eligible. That was too broad: unknown scope
is not positive target-scope evidence. The 57-row seed therefore contained
51 out-of-scope rows and 6 valid drinks.

The manual canary produced this exact live state:

- 6 valid drinks approved and published;
- 7 flowers/plants approved and published incorrectly;
- 38 out-of-scope rows still pending;
- 6 out-of-scope rows already rejected.

## Repair contract

The content-addressed repair manifest binds all 57 Review identities and the
13 published offer identities. The repair:

- preserves the six valid drink publications;
- rejects the 38 pending out-of-scope rows;
- retracts the seven invalid publications and rejects their Review rows;
- keeps the six already rejected rows unchanged;
- preserves all seven manual-review `SourceSnapshot` records as audit history;
- stores the full retracted offer payload in the append-only reject revision;
- supports exact replay and exact rollback;
- refuses to run if any identity, status, publication or dependency drifts.

The old `seed-reconciled-review` v1 write path is fail-closed because its plan
does not contain explicit positive target-scope classification. A future weekly
workflow must use a scope-classified plan before Review seeding is re-enabled.

## Expected final state

For the B15H6 plan:

- approved: 6;
- rejected: 51;
- open: 0;
- published: 6;
- invalid published offers remaining: 0.

The repair does not install or modify systemd timers and does not write to the
Lidl corpus or staging trees.
