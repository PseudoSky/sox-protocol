# SPDX-License-Identifier: Apache-2.0
"""SOX Protocol — reference Python implementation."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("sox-protocol")
except PackageNotFoundError:  # pragma: no cover — only hit when running from a source checkout without `pip install -e`
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
