#!/usr/bin/env python3
"""CLI entrypoint for the Tree Decompose Development Engine.

Usage:
    python tree-decompose.py --dry-run
    python tree-decompose.py --diagnostic "npx tsc --noEmit"
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the local engine package is importable.
package_root = Path(__file__).resolve().parent
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))

from engine import orchestrator


if __name__ == "__main__":
    sys.exit(orchestrator.main())
