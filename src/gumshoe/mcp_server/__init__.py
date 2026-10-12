"""The MCP server: tools over a game. See docs/superpowers/specs/2026-10-12-mcp-server-3-design.md.

`GameHost` holds the games and does all the work; `tools` registers it with the `mcp` SDK. This
package imports only `gumshoe.cases` (its public face), the stdlib, pydantic and, in `tools` and
`__main__`, the `mcp` SDK. It reaches the case engine
only through `gumshoe.cases` (the public face), keeps a case only as its canonical bytes between
calls, and never imports the decider.
"""

from gumshoe.mcp_server.errors import GameError
from gumshoe.mcp_server.host import GameHost, IdSource, NewGame
from gumshoe.mcp_server.saves import SaveRef

__all__ = ["GameError", "GameHost", "IdSource", "NewGame", "SaveRef"]
