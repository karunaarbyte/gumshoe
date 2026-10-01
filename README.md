# Gumshoe

A detective-mystery game built to try out TypeSafe's **Jev** decision model (hosted) next to **Nimble**
(open, local via Ollama) as the decision layer of an MCP-based agent.

Status: decision client done (`src/gumshoe/decider/`). Case engine, MCP server, agent loop and frontend are next.

## Setup

```bash
uv sync                      # creates .venv with Python 3.13 and installs dependencies
cp .env.example .env         # then fill in JEV_API_KEY (never commit .env)
ollama pull nimble           # needs Ollama >= 0.35 for the local decision model
```

## Try the decision layer

```bash
uv run python -m gumshoe.decider ask "I search the study for fingerprints"
uv run python -m gumshoe.decider compare "I accuse the butler!"     # Jev vs Nimble side by side
```

## Checks (run all four before committing)

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
uv run pytest -m live        # opt-in: calls the real backends
```

## Layout

`src/gumshoe/decider/` is layered: `contract/` (pure types) <- `backends/` (HTTP, factory) <- `tools/` (CLI).
The import rules are written in `decider/__init__.py` and enforced by `tests/test_architecture.py`.
