"""pytest configuration for workflow_lint tests.

Adds the repo root to ``sys.path`` so the ``tools`` package (and thus
``tools.workflow_lint``) can be imported. This matches the dotted name used
by the universal ``code-python`` exit criterion (``--cov=tools.workflow_lint``).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
