"""Run030 probe with the accepted target-boundary adapter plus frozen-history replay."""
from __future__ import annotations
from contextlib import contextmanager
import os, runpy, sys

import o_native_date_boundary_adapter as boundary
from o_frozen_history_retrieval_adapter import patched_yahoo_frozen_history
from o_native_context_canonical import install_into_semantic_contract
from deepseek_flash_cap010_guard import install_into_budget_guard

def _arg(name):
    try:return sys.argv[sys.argv.index(name)+1]
    except (ValueError,IndexError):raise ValueError("MISSING_"+name.lstrip("-").upper())

def main():
    preflight=_arg("--preflight")
    original=boundary.patched_yahoo_target_boundary

    @contextmanager
    def combined(target_session):
        with original(target_session) as a:
            with patched_yahoo_frozen_history(preflight) as f:
                merged=dict(a)
                merged["frozen_history_enabled"]=True
                merged["frozen_history_expected_count"]=f["expected_count"]
                yield merged

    boundary.patched_yahoo_target_boundary=combined
    os.environ["DSA_FROZEN_HISTORY_AUDIT_PATH"]=os.environ.get("DSA_FROZEN_HISTORY_AUDIT_PATH","/tmp/frozen-history-audit.json")
    install_into_semantic_contract()
    install_into_budget_guard()
    runpy.run_module("run_hk_original_model_probe",run_name="__main__")

if __name__=="__main__":main()
