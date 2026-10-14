# Gumshoe

A detective-mystery game built to try out TypeSafe's **Jev** decision model (hosted) next to **Nimble**
(open, local via Ollama) as the decision layer of an MCP-based agent.

Status: the case engine, the MCP game server, the agent loop and the HTTP API (game and stats) are in;
the React UI is next.

## Setup

```bash
uv sync                      # creates .venv with Python 3.13 and installs dependencies
cp .env.example .env         # then fill in JEV_API_KEY (never commit .env)
ollama pull nimble           # needs Ollama >= 0.35 for the local decision model
ollama pull ministral-3:14b  # the suspects' voice (PERSONA_MODEL_DEFAULT)
ollama pull gemma4:12b       # the voice for dramatic moments (PERSONA_MODEL_DRAMATIC)
```

Without a Jev key yet, uncomment the two role lines in `.env` to play on Nimble alone (see `.env.example`).

## Try the decision layer

```bash
uv run python -m gumshoe.decider ask "I search the study for fingerprints"
uv run python -m gumshoe.decider compare "I accuse the butler!"     # Jev vs Nimble side by side
```

## Shadow mode: Jev vs Nimble on every decision

With a Jev key in `.env` (and no `DECIDER_PRIMARY`/`DECIDER_SHADOW` overrides), every decision runs on Jev
(used by the game) and Nimble (shadow, recorded only) concurrently. If Jev fails, Nimble's answer is used and
the decision is flagged `fallback`. Latency, tokens, confidence and agreement go to `data/decisions.db`.

```bash
uv run python -m gumshoe.stats battery --rounds 3   # push 36 sample decisions through both backends
```

## The API: the game and the stats

```bash
uv run gumshoe-api                 # or: uv run python -m gumshoe.api; http://127.0.0.1:8000 (docs at /docs)
uv run gumshoe-api --port 8001 --reload
```

Host and port default to `API_HOST` and `API_PORT`. There is no authentication: keep it on the loopback
address. Cross-origin access is off unless `CORS_ORIGINS` lists exact origins; in development the Vite
dev server proxies `/api`, so none is needed.

- Games: `POST /api/games` `{seed, preset}`, `GET /api/games`, `GET /api/games/{id}` (brief, notebook,
  outcome, the waiting confirmation, the reveal once over), `POST /api/games/{id}/turn` `{text, pending_id?}`
  and `POST /api/games/{id}/confirm` `{pending_id, answer}` (both stream server-sent events, ending with
  `done`), `GET /api/games/{id}/turns` (the transcript), `POST /api/games/{id}/save`, `POST /api/games/load`
  `{name}`, `DELETE /api/games/{id}`, `GET /api/saves`.
- Server: `GET /api/health` (whether the game is on, and why not), `GET /api/meta`.
- Stats: `GET /api/stats/decisions`, `GET /api/decisions` (`?ids=`, `?disagree=true`),
  `GET /api/decisions/{id}`. Set the `*_USD_PER_MTOK_*` prices to see estimated cost.

One turn runs at a time per game (a second one is refused with 409 `turn_in_progress`). Every error body
is `{code, message}`. Games live in memory: a restart ends them, so save the ones to keep. The full
contract is in `docs/superpowers/specs/2026-10-13-api-contract.md`. Stats are aggregated in Python from
SQLite, which is comfortable for tens of thousands of decisions, not millions.

## The MCP game server

```bash
uv run python -m gumshoe.mcp_server --saves saves    # the game as MCP tools over stdio
```

## Case engine

```bash
uv run python -m gumshoe.cases validate tests/cases/golden/manor_small.json --profile custom
```

Validates a detective case against the rule groups (add `--dev` to show spoiler issues and
`--pack pack.json` for the pack-bound rules). Exit code 0 is clean, 1 has errors, 2 is unreadable input.

```bash
uv run python -m gumshoe.cases play tests/cases/golden/manor_small.json      # play it in the terminal
uv run python -m gumshoe.cases simulate tests/cases/golden/manor_small.json  # dev report
```

`play` is menu-driven (numbers, or typed names when you accuse) and shows only what a player may
see; you get three accusation attempts with count-only feedback. It refuses a structurally broken
case (exit 2). `simulate` is a developer report: whether the case is solvable by deduction, the
fewest source uses that decide it, and the exact win rate of a player who reads everything and
then guesses. Note: `import gumshoe.cases` now pulls in the decider stack (through `play/parse.py`).

## Checks (run all four before committing)

```bash
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy && uv run pytest
uv run pytest -m live        # opt-in: calls the real backends
```

## Layout

`src/gumshoe/` holds, from the bottom up: `decider/` (Jev and Nimble behind one contract, with shadow mode;
layered `contract/` <- `backends/` <- `tools/`), `stats/` (the SQLite store and the comparison report),
`cases/` (the case engine: model, rules, generator, play session), `mcp_server/` (the game as MCP tools, and
saves), `agent/` (one player message as one turn: understand, confirm, act, voice a suspect) and `api/`
(FastAPI: the game over server-sent events, and the stats). The import rules are enforced by
`tests/test_architecture.py`.
