#!/usr/bin/env python3

from __future__ import annotations

import os
import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SKILL_ROOT", str(ROOT))

runpy.run_path(str(ROOT / "runtime" / "orchestrator.py"), run_name="__main__")
