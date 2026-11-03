#!/usr/bin/env python3
"""Status board CLI: python3 -I tools/status.py --day N [--watch --lanes a,b] [--claim LANE MODE] [--mark ...]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from race import status  # noqa: E402

sys.exit(status.main())
