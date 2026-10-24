"""sextant: a knowledge base that is a real MCP server.

One top level for the whole project. Until 0.9.0 it was three -- `tools`,
`mcp_server` and `eval` -- which is fine inside a checkout and not fine in
anybody else's `site-packages`, where all three names are already taken by
other distributions on PyPI.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sextant-kb")
except PackageNotFoundError:  # a source tree with nothing installed
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
