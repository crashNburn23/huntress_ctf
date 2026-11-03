#!/usr/bin/env python3
"""Runner entry point (launch.py starts it detached): python3 -I tools/run.py --day N [--wait] [--lanes a,b] [--dry]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from race import runner  # noqa: E402

sys.exit(runner.main())
