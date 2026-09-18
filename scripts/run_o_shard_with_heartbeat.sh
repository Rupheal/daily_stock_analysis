#!/usr/bin/env bash
set -euo pipefail

# Usage:
# run_o_shard_with_heartbeat.sh OUT_DIR <runner args...>
# Runs the Python shard runner in the background and prints a sanitized progress
# heartbeat every 60s from SHARD_RESULT.json. No raw model content is printed.
out_dir="$1"; shift
mkdir -p "$(dirname "$out_dir")"

python scripts/run_hk_o_operational_shard_v3.py "$@" --out "$out_dir" &
pid=$!

heartbeat() {
  python - "$out_dir/SHARD_RESULT.json" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])
if not p.exists():
    print("O_SHARD_HEARTBEAT rows=0 confirmed=0 core=0 shared_stop=None", flush=True)
else:
    try:
        d=json.load(open(p))
        print(
            "O_SHARD_HEARTBEAT"
            f" rows={len(d.get('members') or [])}"
            f" attempted={d.get('attempted_members',0)}"
            f" confirmed={d.get('model_http_requests_confirmed',0)}"
            f" core={d.get('core_accepted',0)}"
            f" shared_stop={d.get('shared_stop_reason')}",
            flush=True,
        )
    except Exception as exc:
        print("O_SHARD_HEARTBEAT parse_pending="+type(exc).__name__, flush=True)
PY
}

while kill -0 "$pid" 2>/dev/null; do
  heartbeat
  sleep 60
done

set +e
wait "$pid"
rc=$?
set -e
heartbeat
exit "$rc"
