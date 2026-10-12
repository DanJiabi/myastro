"""python -m myastro 入口（launchd/脚本调用用）。"""
import sys

from .cli import main

sys.exit(main())
