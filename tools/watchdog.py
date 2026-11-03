#!/usr/bin/env python3
"""Watchdog entry point: python3 -I tools/watchdog.py --day N [--lanes a,b] [--quiet 20] [--fixer-quiet 90]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from race import watchdog  # noqa: E402

sys.exit(watchdog.main())
