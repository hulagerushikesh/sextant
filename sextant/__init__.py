"""sextant: a knowledge base that is a real MCP server.

One top level for the whole project. Until 0.9.0 it was three -- `tools`,
`mcp_server` and `eval` -- which is fine inside a checkout and not fine in
anybody else's `site-packages`, where all three names are already taken by
other distributions on PyPI.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sextant-kb")
except PackageNotFoundError:
    # The Claude Desktop bundle carries this source without installing it, so
    # there is no package metadata; `bundle/build.py` writes the version in
    # beside it. 0.10.0's bundle told its host it was "0.0.0+unknown".
    try:
        from sextant._bundle_version import VERSION
    except ImportError:  # a source tree with nothing installed
        VERSION = "0.0.0+unknown"
    __version__ = VERSION

__all__ = ["__version__"]
