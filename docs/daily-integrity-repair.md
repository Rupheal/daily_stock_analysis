# Complete-session integrity repair (isolated variant)

Baseline: upstream 089d9d26d68f8b839ea5a74a3784e4402925f8b7.
This variant is not the unmodified original DSA. It deliberately analyzes complete
daily sessions only; it does not provide intraday quote-based signals.

## Root causes verified with Xiaomi HK01810

- `_augment_historical_with_realtime` skips non-trading days, while
  `_enhance_context` previously overlaid a quote regardless of market phase.
  The result mixed historical indicators with another price and runtime date.
- Missing open/high/low values were synthesized from previous close/current
  price. This produced open greater than high and zero amplitude.
- `_enhance_context` retained the historical `yesterday` row after overlaying
  `today`; quote percentage and calculated change used different bases.
- The empty-news prompt asserted no news was found even when no search ran.
- The pipeline accepted latest stored bars without requiring the expected
  trading date. Source fallback success did not establish freshness.

## Repair behavior

- Validate daily session date and OHLC before both pipeline decision branches.
- Use complete daily bars for trend analysis and context; keep fetched quotes
  outside decision inputs. Do not create replacement bars or inferred OHLC.
- Validate percentage/bias arithmetic before the legacy model request.
- Require news evidence in the legacy path, using per-source evidence metadata
  rather than nonempty formatted search headings. Agent reports without evidence
  are rejected after the agent finishes (this does not prevent agent call costs).
- Invalid inputs raise a data-integrity error. Existing pipeline error handling
  marks the stock unsuccessful; no successful trading report is produced.
- Empty-news wording says evidence is missing, not that no news exists.

## Validation and limits

26 focused offline tests passed (15 repair cases and 11 context prompt cases).
Changed Python files compiled. Original Xiaomi snapshot is deterministically
blocked for date mismatch, estimated OHLC, OHLC bounds, change percentage, and
MA5/MA10 bias contradictions. No live model requests or paid data retrieval.

The full backend gate, all API/Web/Agent paths, and a live successful end-to-end
report have not been validated. Existing intraday-overlay tests describe the
original behavior and are not acceptance criteria for this complete-session
variant. Deployment requires review of that deliberate behavior change.

Missing 2026-09-11 source bars and news are not fabricated or replenished by this
patch. Quote timestamps, corporate-action adjustments, news freshness, free-form
LLM position contradictions, and provider token accounting need separate work.
Arithmetic disagreement after a corporate action is blocked pending verification,
not automatically treated as a provider error or silently corrected.

No model, source subscription, secret, schedule, or GitHub deployment was changed.
Rollback: continue using the original pinned checkout; this worktree is isolated.
This is a new bilingual scope document; no existing translated document changed.

## Review branch

The repair is published separately as `fix/daily-data-integrity` with the existing
main commit as parent. Main and its fixed-upstream manual acceptance workflow
remain unchanged. Running that original workflow, even after selecting this
branch, still checks out the pinned upstream source and does NOT test this repair.
Use an explicit checkout of the repair commit for offline validation:

```bash
python -m pytest tests/test_daily_integrity_repair.py tests/test_analysis_context_pack_prompt.py -q
```

The classic path reuses the validated daily context instead of reading the
database twice. Trend history ends at the expected daily session. Partial bars
and malformed dates are rejected. No live analysis was dispatched for this branch.
