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
uv run gumshoe-api                 # or: uv run python -m gumshoe.api; http://127.0.0.1:8000 (docs at /docs only with API_DOCS=true)
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

## Running it publicly

Gumshoe has no accounts, no CAPTCHA and no web application firewall. What protects a public copy is the
list below: a signed session cookie, an Origin check, per-session and per-IP limits, a Jev token budget,
and an admin token for the stats. Run it behind one trusted tunnel (for example a Cloudflare Tunnel) and
keep `API_HOST` on `127.0.0.1`.

1. Build the UI: `cd frontend && npm run build`. The API serves `frontend/dist` (`UI_DIST`) at `/` with the
   security headers (a Content-Security-Policy among them); without a build it answers the API only.
2. Set these in `.env` (see `.env.example` for every setting and its default):
   - `PUBLIC_ORIGIN`: the site's own `https://` origin. It turns on the Secure `__Host-` session cookie,
     HSTS and the strict Origin check (a POST or DELETE without the site's Origin gets 403).
   - `SESSION_SECRET`: 32 or more characters; the server will not start without it in public mode.
     Generate: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. Changing it ends every
     session and orphans every save's owner.
   - `ADMIN_TOKEN`: 32 or more characters, no leading or trailing whitespace (same generator). Without it
     the stats routes answer a plain 404 to everyone. The Stats page is not linked from the title screen:
     open `/#/stats` and paste the token (kept in that tab only).
   - `TRUST_PROXY=true`, only behind exactly one trusted proxy: the client IP is then read from
     `X-Forwarded-For` for the per-IP limits. Leave it false otherwise, as the header is spoofable.
   - `JEV_DAILY_TOKENS` (default 5,000,000 per UTC day) and `JEV_IP_DAILY_TOKENS` (default 300,000 per
     client IP): the Jev budget; `0` means no cap. Over a cap, Nimble alone decides until 00:00 UTC ("slow
     mode"). Nimble shares the machine with the persona models, so a decision can take 12 to 26 seconds
     then (measured in `docs/notes/jev-vs-nimble.md`).
   - Expiry: `GAME_IDLE_MINUTES` (30; an idle game closes and its owner gets 410 "cold"),
     `SAVE_RETENTION_DAYS` (30) and `DECISION_RETENTION_DAYS` (30). `0` keeps things forever.
   - Limits per session (`SESSION_*`) and per IP (`IP_*`), plus `MAX_GAMES`, `MAX_PARALLEL_TURNS` and the
     turn queue; defaults are in `.env.example`, `0` means unlimited.
   - `API_DOCS` stays `false` (the default). The server refuses to start with `API_DOCS=true` and
     `PUBLIC_ORIGIN` set.
3. Start it: `uv run gumshoe-api` (one process, bound to `127.0.0.1:8000`).
4. Start the tunnel pointing at `http://127.0.0.1:8000`, then check `https://<your site>/api/health`.

Run a single process: do not use multiple workers or several copies. The open games, the rate-limit
tables and the turn queue live in that process's memory.

What lives where:

- In memory, lost on restart: open games, sessions' counters, rate limits, the turn queue. A restart ends
  every game in progress; saved games survive.
- On disk: saves (`SAVES_DIR`) with an owner file beside each, and the stats and decisions database
  (`STATS_DB_PATH`) with the Jev usage ledger.

Privacy: every message a player types is stored as part of a decision, so the models can be compared. The
title screen says so. Decisions are kept 30 days by default (`DECISION_RETENTION_DAYS`), and the admin
token is the only way to read them. There are no accounts; a player is a signed cookie.

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
