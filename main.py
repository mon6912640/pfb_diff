#!/usr/bin/env python3
"""PfbDiff 统一入口 — 有参数走 CLI，无参数启动 GUI"""

import sys

from pfb_diff import main as cli_main
from gui import run_gui

if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(cli_main())
    else:
        run_gui()
