#!/usr/bin/env python3
"""Print the lane split across fixer sessions: python3 -I tools/sessions.py [--sessions N]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from race import sessions  # noqa: E402

sys.exit(sessions.main())
