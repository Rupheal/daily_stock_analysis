"""Run the frozen original probe with an explicit frozen-history retrieval layer."""
from __future__ import annotations
from contextlib import contextmanager
import os, sys

from o_frozen_history_retrieval_adapter import patched_yahoo_frozen_history
from o_native_context_canonical import install_into_semantic_contract
from deepseek_flash_cap010_guard import install_into_budget_guard

def _arg(name):
    try:return sys.argv[sys.argv.index(name)+1]
    except (ValueError,IndexError):raise ValueError("MISSING_"+name.lstrip("-").upper())

def main():
    preflight=_arg("--preflight")
    install_into_semantic_contract()
    install_into_budget_guard()

    # Import the actual probe module, then replace the exact global looked up by
    # its main() function. This avoids import-cache ambiguity from patching only
    # o_native_date_boundary_adapter after the probe has already bound the name.
    import run_hk_original_model_probe as probe
    original_boundary=probe.patched_yahoo_target_boundary

    @contextmanager
    def combined(target_session):
        with original_boundary(target_session) as boundary_audit:
            with patched_yahoo_frozen_history(preflight) as frozen_audit:
                merged=boundary_audit
                yield merged

    probe.patched_yahoo_target_boundary=combined
    os.environ["DSA_FROZEN_HISTORY_AUDIT_PATH"]=os.environ.get(
        "DSA_FROZEN_HISTORY_AUDIT_PATH","/tmp/frozen-history-audit.json")
    probe.main()

if __name__=="__main__":main()
