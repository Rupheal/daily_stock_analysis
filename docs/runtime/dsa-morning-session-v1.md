# DSA morning session repair — isolated candidate

The previous session driver routed Friday formal receipts into Monday ENTRY. The accepted Entry-v1 requires a newly accepted same-day AM report; prior close is preparation only.

## Executable changes

- PREOPEN/ENTRY select the current XHKG decision session. `market_data_session` is the previous XHKG close and `next_session` is the next XHKG session after the decision. XHKG is not a Southbound eligibility calendar.
- O producer accepts `--market-data-session`. Default same-day close behavior is preserved. For a morning candidate use the verified previous XHKG session, a universe effective for the decision session, and a new output directory. The native probe, coverage packet and shard price preflight retain the price date; policy, provider claim identity and new aggregate receipt retain the decision date.
- This runs the existing O provider route; it does not copy a prior formal receipt. Native prompts/scoring and budgets are unchanged. R0 stays the default; no paid run was invoked in this repair.
- Fix the generated scope's missing `no_orders: true`, which the existing shard requires. It does not grant provider permission: cost/calibration, capacity, durable claim and other gates still apply.
- Only a newly produced result receives market/decision metadata and a real generation observation. The result explicitly says `morning_confirmation: NOT_YET_ACCEPTED` for the split-date case. Generation does not establish publication, availability, formal acceptance or current news coverage.
- Session driver reuses consumer timing checks and requires same-day cutoff/availability by 09:25. It reports routing eligibility only; accepted Entry-v1 still verifies the AM binding, acceptance, freeze, quotes, constraints and ledger commands.

## Concrete remaining dependencies

1. Complete decision-session universe with adjustment-effective-date evidence, current identity and exclusions. Source UPDATE_DATE alone is neither effective date nor expiry.
2. New native ranking within the existing authorized cost route; no reuse/relabel of Sep21 WAIT. Original preflight reports incomplete news/risk coverage; a new generation alone cannot settle morning confirmation.
3. Publisher/consumer availability and formal AM acceptance evidence bound to the new receipt bytes. The existing timing seal can validate supplied evidence but cannot manufacture it. `valid_until` and `next_session` must be sourced, never inferred from file mtime.
4. U's separate producer is unchanged: formal macro cap/risk/zone remain missing. It must not inherit O's split-date policy silently.
5. Live workflows 136/139 remain on their existing bindings. Before approved rollout, supply current decision/previous-price parameters, publish new morning outputs and pass actual Entry-v1 evidence. No workflow/Production switch was performed.

## Validation

72 distinct targeted tests passed (20 existing calendar warnings): morning preflight, formal packet, session driver, accepted Entry-v1 integration and orchestrator. Source dates, stale universes, false coverage dates, invalid timing, price disagreement and prior-PM rejection are covered. Fixtures are synthetic; no natural cycle credit. Python compilation passed. No GitHub CI or Alienware execution is claimed.

## Rollback and compatibility

Revert this candidate commit. No formal journal or runtime binding changed. Same-day O remains compatible; morning driver consumers must use the separate `market_data_session` and current `target_session`. The driver result is not an Authority receipt. The topic has no existing translated twin; this document is the single engineering specification.
