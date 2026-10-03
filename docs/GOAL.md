# Hermes Deals — product goal and Web UI north star

> **Status:** product-vision / UX north-star document.  
> This document describes **why Hermes Deals exists** and **what the family-facing product should ultimately enable**. It does **not** override the canonical technical Web architecture in [`WEB_ARCHITECTURE.md`](WEB_ARCHITECTURE.md), [`ARCHITECTURE.md`](ARCHITECTURE.md), `.github/web-architecture-v1.json`, or the active GitHub execution roadmap.

## Product thesis

> **Tell Hermes what the household needs; Hermes tells you what to buy, where, and why, using current local offers.**

Hermes Deals is not intended to be only a weekly-flyer viewer or a generic deal feed. The target product is a **self-built family grocery-intelligence system** that turns trustworthy local retailer evidence into practical household decisions.

The household should not have to manually compare several flyers, remember historical prices, normalize package sizes, calculate unit prices, decide whether an advertised discount is actually good, then rebuild the same reasoning in a shopping list and meal plan.

Hermes should do that work from authoritative data and present a clear answer:

- **what** is worth buying;
- **where** it is worth buying;
- **why** that choice is good;
- **when** the offer is valid;
- **what constraints apply** (store, app, coupon, loyalty, package size, validity);
- **how the choice affects the whole household basket**, not just one isolated product.

## Why we are building it

The original project direction was deliberately custom. Hermes Deals should not become a skin around KitchenOwl, Mealie, Bring, KaufDA, MeinProspekt, or another finished product/aggregator.

Ideas and UX patterns may be borrowed, but the following remain under Hermes control:

- UI and household workflow;
- retailer/source integrations;
- evidence and provenance model;
- product identity and normalization;
- price-history semantics;
- comparison and scoring logic;
- shopping-list behavior;
- later basket/store optimization;
- recipe and meal-planning integration.

The original family-delivery decision also favored a **Web UI**. Telegram was considered inconvenient for the complete workflow, while Google Keep was only a temporary shopping-list solution rather than the final product model.

## Historical UI north star

The following early concept captures the intended **family-facing outcome** of Hermes Deals. It is a product/UX reference, not a requirement to preserve every pixel or the historical frontend stack.

![Historical Hermes Deals dashboard concept](assets/hermes-deals-ui-goal.webp)

*Historical concept: one household dashboard combining weekly store intelligence, personal deals, meal ideas, shopping list, and price history.*

### What this concept is trying to achieve

The screenshot places the user in one clear context:

**this household + this location + this week.**

Instead of forcing the user to browse retailer data first, the UI starts with the household decision.

### 1. Overview / command center

The home screen should answer the most useful weekly question immediately:

> **Where is it most advantageous for us to shop this week?**

The historical concept shows a store comparison across Lidl, Netto, ALDI Nord and EDEKA with a score and estimated savings. The important idea is not the exact score design; it is that Hermes should summarize raw retailer data into a useful household-level decision.

The dashboard should eventually surface:

- best store / store combination for the household;
- estimated savings;
- important validity or coupon constraints;
- unusually good prices for products the household actually cares about;
- shopping-list implications;
- meal opportunities created by current deals.

### 2. Deals that matter to this household

The concept includes **“Tieši jums izdevīgi piedāvājumi”** rather than only a generic catalogue.

For each relevant deal Hermes should be able to explain:

- product;
- retailer/store;
- current price;
- normal/reference price when trustworthy;
- discount or deal-quality signal;
- absolute savings;
- package / unit price;
- validity;
- app/coupon/loyalty requirement where applicable;
- provenance-backed product identity.

The long-term objective is relevance, not maximum catalogue volume.

### 3. Shopping list as an intelligence surface

The shopping list should be more than a checklist.

A household member should be able to add an intent such as “milk”, “chicken”, or a specific product and let Hermes help determine:

- the appropriate canonical product or substitutable product group;
- current matching offers;
- best unit/package value;
- preferred store constraints;
- whether splitting the basket across stores is worthwhile;
- the final recommended store trip or basket plan.

The list is therefore one of the main inputs to Hermes intelligence, not a separate utility bolted onto the app.

### 4. Price history: “is this actually a good price?”

A displayed `-30%` label is not enough.

Hermes should use reviewed historical observations to help distinguish:

- a genuinely strong price;
- a routine promotional price;
- a misleading nominal discount;
- a package-size change that makes the headline price incomparable;
- a good price at one retailer versus the current cross-store alternative.

Price history should therefore support both product detail and household decision-making.

### 5. Meal planning from real weekly offers

The early concept includes **“Ko gatavot šonedēļ?”** with meal ideas, cost per portion and the number of ingredients currently on promotion.

That expresses the Phase 6 product direction well: recipes are not an isolated recipe database. They should connect to the same current retailer truth used elsewhere in Hermes.

A useful future recipe/meal-planning flow can answer:

- what meals are economical this week;
- which ingredients are already on the shopping list;
- which ingredients have strong current offers;
- approximate cost per portion;
- which retailer trip best supports the planned meals;
- how a weekly meal plan rolls up into the shopping list.

## Intended information architecture

The historical concept proposed the following family-facing areas:

- **Pārskats** — household command center;
- **Piedāvājumi** — current/upcoming retailer offers and filters;
- **Iepirkumu saraksts** — shared household shopping intent and basket planning;
- **Ēdienkarte** — weekly meal plan;
- **Receptes** — recipes connected to current offers and household needs;
- **Mīļākie produkti** — products the household actively tracks;
- **Cenu vēsture** — reviewed historical price observations and comparisons;
- **Statistika** — savings / shopping insights where they are genuinely useful;
- **Iestatījumi** — household, retailer, store and preference settings.

The exact navigation may evolve, especially on mobile, but these capabilities describe the intended product surface.

## Product capability progression

The original roadmap maps naturally to the dashboard vision:

1. **Trustworthy retailer evidence and offer persistence**  
   Collect real local offers and preserve immutable source provenance.

2. **Canonical products + price history**  
   Separate retailer observations from reviewed product identity so prices can be compared over time and across stores.

3. **Family preferences + deal scoring**  
   Move from “what is on sale?” to “what matters to this household?”

4. **Basket/store comparison**  
   Evaluate the whole shopping need rather than independent product cards.

5. **Shared shopping list**  
   Turn household intent into a practical, synchronized shopping workflow.

6. **Recipes + meal planner + ingredient aggregation**  
   Connect current offers to real meal decisions and roll ingredients back into the basket.

## Core product loop

The long-term Hermes loop is:

```text
Retailer evidence
    -> validated offer observations
    -> normalized / canonical product identity
    -> current + historical price intelligence
    -> household preferences and shopping intent
    -> deal / basket / store-trip reasoning
    -> shopping list and meal plan
    -> household action
```

The UI should hide unnecessary implementation complexity while preserving the ability to explain consequential recommendations from source evidence.

## UX principles

### Decision first, data second

The app should lead with useful answers and allow users to inspect supporting detail. A family member should not need to understand the collector/parser architecture to decide where to buy milk.

### Trustworthy before clever

A recommendation is only valuable if the underlying retailer, store, validity, price and product identity are trustworthy. Hermes should prefer “unknown / needs review” over invented certainty.

### Household relevance over catalogue volume

More offers are not automatically better. The product should prioritize offers, products and meals that matter to the household.

### Compare compatible things

Package size, quantity, unit basis, pack count, loyalty/app requirements and validity windows matter. Headline price alone is insufficient.

### Explain “why”

When Hermes recommends a deal/store/basket, the user should be able to understand the reason: price history, unit price, current alternatives, savings, preference or constraint.

### Mobile-first family use

The product is expected to be used while planning and while shopping. Mobile navigation, touch targets, keyboard/accessibility behavior, readable density and fast interaction are first-class requirements.

## Current technical Web architecture

The **product goal above remains valid**, but the historical frontend implementation plan has changed.

The current canonical Hermes Deals Web target is server-driven and online-only:

```text
FastAPI + PostgreSQL + Jinja + HTMX
+ semantic HTML + plain CSS
+ minimal Vanilla JS + SSE
+ Cloudflare Access/Tunnel
```

See:

- [`WEB_ARCHITECTURE.md`](WEB_ARCHITECTURE.md)
- [`ARCHITECTURE.md`](ARCHITECTURE.md)
- [`ROADMAP.md`](ROADMAP.md)
- [GitHub issue #319](https://github.com/rozkalnsandris/hermes-deals/issues/319)

The superseded SvelteKit/Tailwind/IndexedDB/Dexie/offline-first/WebSocket-default plan must not be inferred from this historical UI concept.

The browser is a thin presentation/interaction client. Pricing, validity, product identity, comparison, Review semantics and basket intelligence belong in shared Python/PostgreSQL domain services. HTML and JSON are projections of the same authoritative server-side truth.

## What the screenshot means today

Use the historical screenshot as a **UX north star**, specifically for these ideas:

- one coherent household application instead of disconnected technical tools;
- weekly/local context visible immediately;
- decision-oriented overview;
- retailer comparison;
- personalized relevant deals;
- integrated shopping list;
- useful price history;
- meal ideas driven by real current offers;
- clean, high-density but understandable presentation.

Do **not** treat it as authority for:

- the exact historical component layout;
- exact store scores shown in the mockup;
- example prices or savings shown in the mockup;
- the old frontend framework/runtime choice;
- invented data that is not supported by current retailer evidence.

## Definition of the long-term product outcome

Hermes Deals succeeds when the household can start from a practical need rather than a retailer flyer:

> “This is what we need this week.”

and Hermes can turn trustworthy current local data into an understandable plan:

> “Buy these items here, these items there, this is approximately what the basket costs, this is why the choice is good, and these meal options fit the same week.”

The objective is **not to show the household more grocery data**.

The objective is to **reduce the work required to turn grocery data into a good household decision**.
