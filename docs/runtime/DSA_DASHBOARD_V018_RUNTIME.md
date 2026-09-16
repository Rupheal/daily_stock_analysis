# DSA Dashboard v0.18 runtime contract

## Purpose

v0.18 separates engineering/runtime telemetry from strategy acceptance. The browser consumes a sanitized repository feed and must never read Drive raw evidence, model raw request/response, API keys, GitHub PATs, or provider secrets.

## Primary feed

`DSA_DASHBOARD_LIVE.json` is the single primary live-state contract. It contains `meta`, `system`, `O`, `U`, `data_health`, `observer`, `storage`, `budget`, `simulation`, `shadow_week`, and `debug`.

The UI does not depend on RUN018, Workflow 52, a fixed GitHub Actions run id, or a fixed CHILD id. It does not call the GitHub Actions REST API. Its only runtime data fetches are the sanitized live feed and the append-only Shadow Week history file.

## State semantics

- `LIVE`: current sanitized feed is fresh and schema-valid.
- `LAST_VALIDATED`: previously validated strategy/runtime evidence retained while no newer accepted result exists.
- `STALE`: feed exists but is older than the UI freshness window.
- `OFFLINE SNAPSHOT`: the current fetch failed; previously loaded validated state is retained in memory instead of being erased.
- `WAIT`: a valid no-action signal; it is not a failure.
- `NOT_VERIFIED`: no authoritative value is available; never render numeric zero as a substitute.
- `BLOCKED`: a hard gate is unresolved.

## Refresh/fail-safe

The UI refresh interval is five minutes. Feed age above 36 hours is marked `STALE`. Malformed/incomplete feeds fail closed. A fetch failure preserves the previously loaded validated state and marks it `OFFLINE SNAPSHOT`.

## Shadow Week

`DSA_DASHBOARD_HISTORY.json` is append-only by date. `scripts/dashboard_feed_generator.py` will not replace an existing date. The history is telemetry only and cannot promote O/U strategy acceptance.

## Governance

- U denominator remains 45 unless a separately authorized operating agreement changes it; failed members remain visible.
- `PREP_READY` is not `Formal Accepted`.
- Simulation values remain `NOT_VERIFIED` unless an authoritative simulation ledger exists.
- Dashboard work grants no model/provider authorization.
- No main merge or runtime activation follows from Dashboard acceptance.
