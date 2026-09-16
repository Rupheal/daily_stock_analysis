"""Run028 bootstrap for one separately authorized Gate-A provider attempt.

It composes two previously bounded external acceptance-layer changes: typed
native-context hashing and a pre-send CNY 0.10 DeepSeek Flash cost gate.  Frozen
upstream source, prompt construction, model parameters and strategy are not
edited here.
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
