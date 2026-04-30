"""pytest configuration for workflow_lint tests.

Adds the repo's ``tools/`` directory to sys.path so ``import workflow_lint``
works without packaging.
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
