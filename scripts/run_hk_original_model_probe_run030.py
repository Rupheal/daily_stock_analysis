"""Run030 bootstrap for one independent Gate-A provider attempt.

It reuses the frozen original DSA plus the external typed context hash,
DeepSeek pre-send cost guard, and the versioned HK retrieval boundary adapter.
No frozen upstream prompt, scoring, model parameters, or strategy logic changes.
"""
from __future__ import annotations

import runpy

from o_native_context_canonical import install_into_semantic_contract
from deepseek_flash_cap010_guard import install_into_budget_guard


def main():
    install_into_semantic_contract()
    install_into_budget_guard()
    runpy.run_module("run_hk_original_model_probe", run_name="__main__")


if __name__ == "__main__":
    main()
