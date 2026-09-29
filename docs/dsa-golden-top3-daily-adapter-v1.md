# Golden DSA HK Top3 Daily Adapter v1

## Purpose

`Golden DSA HK Top3 Daily Adapter v1` is a **read-only projection seam** for downstream DSA consumers.

It does not run O or U, does not rank stocks, does not reinterpret Top10, and does not create a BUY. It consumes the current-session formal O/U receipts selected by the existing `dsa_formal_receipt_resolver_v1`, reuses the Production Orchestrator classifiers, and emits one deterministic daily envelope.

## Public interface

Python:

```python
from pathlib import Path
from scripts.dsa_golden_top3_daily_adapter_v1 import build_golden_daily

result = build_golden_daily(Path("."), "YYYY-MM-DD")
```

CLI:

```bash
python scripts/dsa_golden_top3_daily_adapter_v1.py \
  --target-session YYYY-MM-DD \
  --out artifacts/golden-top3/YYYY-MM-DD.json
```

The output path is derivative evidence only. It is not an Authority ledger, runtime pointer, simulation journal, or deployment receipt.

## Source authority

The adapter delegates source selection to the existing formal receipt resolver:

- O: current-session formally usable O receipt
- U: current-session formally usable U receipt
- stale or missing current-session receipts: fail closed

The adapter then delegates O/U semantic classification to the existing Production Orchestrator classifiers. It intentionally does **not** duplicate their acceptance or BUY logic.

## Output contract

Top-level fields:

- `schema_version = 1`
- `adapter_version = GOLDEN_DSA_HK_TOP3_DAILY_ADAPTER_v1`
- `market = XHKG`
- `target_session`
- `state = READY` only after both current-session formal receipts resolve and classify as consumable
- `decision_state = WAIT_NO_BUY | QUALIFIED_BUY_PRESENT`
- `authority = NONE_PROJECTION_ONLY`
- `tracks.O` and `tracks.U` kept independent
- exact source receipt paths and SHA-256 digests
- deterministic receipt SHA-256
- explicit zero side effects

Each Top3 row exposes only:

`code, name, rank, score, industry, action, buyable_verified`

The adapter never exposes private provider content.

## Fail-closed rules

The adapter rejects:

- missing/stale formal receipts
- semantic source drift between resolver selection and exact-byte hashing
- blocked/stale O or U classification
- more than three Top3 rows
- missing or duplicate Top3 codes
- invalid Top3 ranks
- mismatch between classifier-qualified BUY count and projected BUY rows
- output paths escaping the supplied repository root

U `Top10` is never promoted into `Top3`. An accepted U WAIT with empty Top3 remains empty.

## Boundaries

This adapter has no permission to:

- change O/U model, prompt, scoring, ranking, thresholds, universe, or evidence rules
- call a model/provider
- modify schedule or runtime pointers
- issue Signal/Entry commands
- write the simulation journal
- place broker or real orders
- merge main or promote Production

Execution remains behind the existing Production Orchestrator / Entry-v1 / governed runtime seams.

## Validation seam

The retained tests exercise the public `build_golden_daily(root, target_session)` interface and cover:

1. O/U isolation and no U Top10 promotion
2. projection of an already-qualified BUY without creating execution authority
3. missing formal receipt fail-closed behavior
4. duplicate Top3 fail-closed behavior
5. deterministic source-hash-bound output
6. no mutation of source formal receipts
7. documented Python package import compatibility
8. resolver-to-source semantic drift fail-closed behavior

Runtime deployment and natural-cycle acceptance are explicitly outside v1 engineering acceptance.
