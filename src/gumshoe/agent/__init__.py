"""The agent loop: free text in, game actions and in-character replies out.

Imports point one way (enforced by tests/test_architecture.py): only this package, the top level
of gumshoe.cases and gumshoe.decider, the stdlib and pydantic; the `mcp` SDK only in game.py and
httpx only in llm.py. It never imports gumshoe.mcp_server: it talks to the game through the MCP
client it is given.
"""
