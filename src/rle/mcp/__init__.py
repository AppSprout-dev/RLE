"""RimAPI as an MCP tool surface for external coding-agent harnesses.

``ledger`` and ``session`` have no ``mcp`` dependency; ``server`` / ``host``
need the ``mcp`` extra. Run standalone with ``rle-mcp`` (stdio) for manual
play against a live game, or let a harness host it in-process (streamable
HTTP) so the ledger and the loop share memory.
"""

from rle.mcp.ledger import NoActiveTickError, TickLedger
from rle.mcp.session import McpSession

__all__ = ["McpSession", "NoActiveTickError", "TickLedger"]
