# DSA Dashboard v0.19 — authority/freshness R&D contract

## Status

IN DEVELOPMENT on branch research/dsa-dashboard-v019-20260918.

v0.18 remains the accepted engineering baseline and is not overwritten. v0.19 is a separate continuation focused on evidence freshness, authority provenance, and the distinction between data readiness and formal strategy acceptance.

## P0 problem fixed in this branch

The accepted v0.18 browser used one root live-feed URL, but repository execution evidence advanced to 2026-09-18 while the v0.18 feed remained anchored to 2026-09-16. A second docs/dashboard/DSA_DASHBOARD_LIVE.json copy also existed, so repository state could be misread as having more than one apparent live snapshot.

v0.19 introduces an explicit authority block and a new canonical development feed:

- DSA_DASHBOARD_LIVE_V019.json
- DSA_DASHBOARD_LIVE_V019.schema.json
- DSA_DASHBOARD_HISTORY_V019.json
- scripts/dashboard_feed_generator_v019.py
- DSA_Dashboard_v0.19_Live_UI.html

The browser still reads sanitized repository data only. It never reads GitHub Actions APIs, Drive raw evidence, prompts/responses, tokens, or secrets.

## Current authority anchor

- receipt: docs/runtime/RUN060_RECOVERED_RESULT.json
- run: TRI-DSA-RESUME-20260918-060-RECOVERED
- workflow run: 35335286449
- target session: 2026-09-18
- O official denominator: 660
- O current data-ready: 657
- O isolated: 3
- U denominator: 45
- U current data-ready: 45
- U Southbound buy-eligible: 44
- formal signal generated: false
- model HTTP requests: 0
- real orders: 0
- simulation writes: 0

These are telemetry facts, not a BUY/SELL recommendation and not strategy acceptance.

## Semantic change

v0.19 shows two separate dimensions:

1. DATA READY — whether the current-session input/data gate has usable coverage.
2. FORMAL — whether the corresponding O/U formal strategy output has been accepted.

For the Run060 anchor, O data-ready is 657/660 and U data-ready is 45/45, while formal accepted remains 0 for both. The UI must never compress these into one misleading coverage number.

## Generator contract

The v0.19 generator is deterministic, network-free and model-free. It discovers compatible RUN*_RESULT.json receipts containing official O/U denominators, target session and formal-signal state; it chooses the newest by session and run number. It hashes the source receipt and fails closed on denominator/coverage invariants or secret-like content.

## Non-goals / frozen boundaries

- no main merge
- no scheduler modification
- no provider/model permission expansion
- no strategy prompt/scoring change
- no simulated or real order
- no rewrite of v0.18 accepted files
- no interpretation of data readiness as formal signal acceptance

## Next acceptance gate

v0.19 is ready for engineering acceptance only after its deterministic tests and v0.18 regression tests pass on GitHub Actions. Strategy acceptance remains a separate gate.
