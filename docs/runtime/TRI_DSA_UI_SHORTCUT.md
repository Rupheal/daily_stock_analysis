# /tri dsa ui shortcut contract

## Exact meaning

When the user enters `/tri dsa ui`, resolve the current DSA Dashboard route before presenting it. This is a read-only display shortcut, not a trading or model-execution command.

## Resolution order

1. Read the v0.19 engineering acceptance and current sanitized feed.
2. Compare v0.19 against the authoritative `fix/native-private-execution-20260914` checkout using `dashboard_feed_lag_detector_v019.py`.
3. If the detector returns `ALIGNED`, route to `DSA_Dashboard_v0.19_Live_UI.html` on `research/dsa-dashboard-v019-20260918` and label it `CURRENT / READ ONLY`.
4. If v0.19 is not aligned/valid/accepted, route to the engineering-accepted v0.18 UI and label it `LAST VALIDATED / READ ONLY`. Always show the fallback reason. Never imply that v0.18 is current data.
5. If neither safe UI exists, return `BLOCKED`; do not invent a route.

## Important semantics

- `SOURCE_AHEAD` means the authority branch has a newer compatible runtime receipt than the v0.19 feed.
- `SOURCE_MISMATCH` means the v0.19 feed disagrees with the receipt it claims to represent.
- A fallback is a UI availability fallback only. It does not change or reinterpret any O/U strategy signal.
- `WAIT` remains a valid no-action state.
- Data readiness and formal strategy acceptance remain separate.
- This shortcut never calls a model/provider, writes a trade, changes a schedule, merges main, or reads Drive/private raw evidence in the browser.

## User-facing response contract

For `/tri dsa ui`, report at minimum:
- selected version,
- route badge,
- authority run/session when v0.19 is aligned,
- explicit fallback reason if v0.18 is selected,
- the selected repository UI path/link.

Do not silently serve a stale version.
