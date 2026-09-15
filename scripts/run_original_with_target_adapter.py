"""Execute the frozen upstream CLI with only the Run018 Yahoo boundary adapter.

Usage:
  python run_original_with_target_adapter.py --checkout original --target 2026-09-15 -- <native args>
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import runpy
import sys

from o_native_date_boundary_adapter import patched_yahoo_target_boundary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('native_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    native_args = list(args.native_args)
    if native_args and native_args[0] == '--':
        native_args = native_args[1:]
    if not (checkout / 'main.py').is_file():
        raise SystemExit('FROZEN_NATIVE_MAIN_MISSING')
    os.chdir(checkout)
    sys.path.insert(0, str(checkout))
    sys.argv = ['main.py'] + native_args
    with patched_yahoo_target_boundary(args.target) as applied:
        try:
            runpy.run_path(str(checkout / 'main.py'), run_name='__main__')
        finally:
            print('O_TARGET_BOUNDARY_ADAPTER_COUNT', applied['count'], flush=True)


if __name__ == '__main__':
    main()
