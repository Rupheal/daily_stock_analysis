"""Bootstrap the existing O-native probe with typed native-context hashing.

This file does not authorize or perform a provider request by itself.  It exists
so a separately authorized future Gate-A execution can reuse the unchanged
probe after deterministic model-free acceptance of the date-context fix.
"""
from __future__ import annotations

import runpy

from o_native_context_canonical import install_into_semantic_contract


def main():
    install_into_semantic_contract()
    runpy.run_module("run_hk_original_model_probe", run_name="__main__")


if __name__ == "__main__":
    main()
