# UI Daily Use v1

## Scope

This isolated UI branch changes only static UI files, UI-only tests, and this document. It does not change the Lidl parser, persistence, schema, collectors, production database, or runtime deployment.

## Review flow

- Review statuses are displayed in Latvian.
- Save, follow-up, publish, reject, and reopen actions show busy state and a non-blocking result message.
- Publish/reject removes the completed row from the open queue and opens the next visible row.
- Closed rows are read-only except for reopening.
- Queue rows are native keyboard-accessible buttons.
- The queue shows the current result count.

## Deals refresh bridge

Publishing from `/ui/review` emits a `BroadcastChannel` message and a `localStorage` fallback event. An already-open `/ui` tab refreshes overview and the current deal page without a full page reload. The main UI also refreshes when it becomes visible again.

## Acceptance

1. Open `/ui` and `/ui/review` in separate tabs.
2. Save a review correction and verify the row stays selected with a success message.
3. Publish an open review item and verify the next open row is selected.
4. Verify the published item disappears from the open queue.
5. Switch to `/ui`; verify the current view refreshes without a browser reload.
6. Select `Publicēts`; verify the published row is visible and only `Atgriezt gaidīšanā` remains actionable.
7. Repeat at mobile width and with keyboard-only navigation.

## Deferred

A real browser E2E suite remains a separate gate because Playwright is not yet installed in this repository.
