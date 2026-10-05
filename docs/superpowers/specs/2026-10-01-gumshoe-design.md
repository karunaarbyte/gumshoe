# Gumshoe — Design Spec

Date: 2026-10-01
Status: Draft for review (sub-project 1 detailed; 2–5 outlined)

## 1. Purpose

A detective-mystery game used to try out **Jev** (TypeSafe's typed decision model) as the
decision layer of an MCP-based agent. Goals, in priority order:

1. Learn Jev properly: classification, tool selection, routing, gating via typed decisions.
2. Compare Jev (hosted) against **Nimble** (open, local, same API) on identical decisions.
3. Learn intermediate Python by building it. **The user writes the code; Claude guides and teaches.**
4. Be a fun, replayable game with randomised cases.

Non-goals: production hardening, auth/multi-user, deployment, persistence beyond a local file.

## 2. Constraints and decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Backend | Python ≥ 3.12 (use `uv`; 3.13 already installed), FastAPI, official `mcp` SDK |
| Frontend | **Open, decided at sub-project 5.** The user is fine with a richer frontend than plain HTML/CSS/JS (update 2026-10-01). Leading option: React + TypeScript + Vite + Tailwind, with a graph/board library for the evidence board and typed API clients generated from FastAPI's OpenAPI. Fallback: vanilla JS + Tailwind CDN |
| Decision models | Hosted Jev and local Nimble both run at **every decision node** (shadow mode, §4a). Roles set by `DECIDER_PRIMARY` (default `jev`) and `DECIDER_SHADOW` (default `nimble`, blank = off). Both speak the Jev API (`state` + named `questions`) |
| Reasoning/text | Ollama: `gemma4:12b` and `ministral-3:14b`, assignable per role via env |
| Jev access | Hosted TypeSafe API, user holds key, pastes into `.env` later |
| Cases | Multiple, seeded randomisation, same seed ⇒ same case |
| Personas | Suspects and narrator driven by persona definitions |
| Learning mode | Small tasks, checkpoint after each, concept lessons attached to tasks |

## 3. Facts verified vs. still to verify

Verified locally: Ollama has `nimble:latest` (qwen35 9B, Q8_0, capability `decision`, needs Ollama ≥ 0.35),
`gemma4:12b`, `ministral-3:14b`. uv installed; Python 3.13 available.

From a fetched summary of Nimble's Ollama page (to be confirmed against real responses in Task 1.2):
endpoint `/v1/systemone`; request `{model, state, questions}`; 1–64 named questions;
types `choice` (2–26 options), `noul` (yes/no), `score` (ordered rubric); responses carry the answer,
probabilities and a confidence value.

**Unverified:** hosted Jev base URL, auth header, exact response JSON. Task 1.2 captures real
responses as fixtures and Task 1.3 confirms Jev's URL/auth from TypeSafe docs before any code
depends on them. No Pydantic model is written from assumption; models are derived from captured fixtures.

## 4. Architecture

```
 Browser (HTML/CSS/JS)
   │  HTTP + SSE (turn stream, trace events)
 FastAPI app ───────────────┐
   │                        │
 Agent loop (per turn)      │ reads/writes
   │  1 intent  ─────────►  Decider  (Jev | Nimble)   typed decisions
   │  2 tool select ─────►  Decider
   │  3 call tools ──────►  MCP server (FastMCP) ──► Case state (seeded case + progress)
   │  4 model route ─────►  Decider
   │  5 narrate / persona ► Ollama (gemma4 | ministral-3)
   │  6 post-check ──────►  Decider
   └─ trace events ───────► SSE to UI
```

Units and boundaries (each understandable and testable alone):

- `decider/`: send state + questions, get typed answers. Knows nothing about the game.
- `cases/`: case schema, seeded generator, validator. Knows nothing about LLMs or MCP.
- `mcp_server/`: tools over a case. Knows nothing about the Decider.
- `agent/`: orchestrates the turn. The only unit that sees all the others.
- `api/` + `web/`: transport and presentation.

Jev decisions in the turn pipeline (design sketch, finalised in sub-project 4). Because one call
accepts up to 64 questions over the same `state`, each stage is **one batched call**, not many:

| Stage | Question type | Example |
|---|---|---|
| Intent | choice | `action / dialogue / accusation / meta / nonsense` |
| Tool select | noul per tool (allows chains) + choice for primary | `needs_search_scene`, `needs_interrogate` |
| Target | choice | which suspect/location the player means |
| Model route | choice / score | `small` vs `large` model; dramatic weight 1–5 |
| Confidence gate | uses probabilities | below threshold ⇒ ask clarifying question |
| Post-check | noul | `contradicts_case_state`, `reveals_culprit_early` |

## 4a. Shadow mode and comparison stats (added 2026-10-01)

Purpose: compare Jev and Nimble on the game's real decisions without letting Nimble affect gameplay.

**Behaviour**
- Every decision node (any call to a decider; `node` label such as `intent`, `tool_select`, `route`, `post_check`)
  runs the **primary** (Jev) and the **shadow** (Nimble) **concurrently** on the same `state` and `questions`.
- **The game uses the primary's result.** The shadow never delays or fails a turn: the game proceeds as soon as the
  primary returns; shadow errors are recorded, not raised.
- **Fallback:** if the primary fails (timeout, 5xx, no key) and the shadow succeeded, the game uses the shadow's
  result and the call is flagged `fallback`. Fallback pairs are excluded from head-to-head aggregates.
  If both fail, the turn fails with a visible error.
- `DECIDER_SHADOW` blank turns shadowing off; primary and shadow must differ.

**Recorded per backend per call** (SQLite `data/decisions.db`, stdlib `sqlite3`; refined in Plan 1b)
- One table `decision_calls`: `decision_id` (shared by the pair), `node`, `backend`, `role` (`primary`|`shadow`),
  `used` (the game used this result), `fallback` (the decision's used result came from the shadow because the
  primary failed), `cold`, `ts`, `latency_ms`, `input_tokens`, `output_tokens`, `mean_confidence`,
  `min_confidence`, `error`, `state_preview`, and `answers_json` (every question's typed answer).
  Agreement is computed in Python from `answers_json` with the shared `answers_agree` function, so there is one
  definition of "agree" (choice: same option; noul: same side of 0.5; score: spread under 0.5 of a level).
- **Cold flag:** a call is `cold` when that backend had no call in the previous 300 s, or none since the process
  started (Ollama unloads idle models). Latency percentiles exclude cold and errored calls by default
  (`include_cold=true` to include cold ones); counts and error rates always include everything.
- **Confidence definition:** choice and score answers use the API's `confidence`; noul answers have none, so
  confidence is `max(p, 1-p)` (0.5 = coin flip, 1.0 = certain).
- **Outcomes of a turn:** primary ok (shadow recorded in the background); primary failed and shadow ok
  (`fallback`, shadow's answer used); both failed (`DeciderAllFailedError`, both recorded, nothing `used`).
  A broken recorder never fails a turn.
- No state text is stored beyond a 200-character preview; the API key never reaches the DB, logs, or errors.
- Layering: `decider/shadow/` holds `ShadowDecider` and the `Recorder` Protocol (imports only `contract/`);
  `gumshoe.stats` implements the Recorder with SQLite and holds the pure aggregation functions;
  `gumshoe.api` is a thin FastAPI layer. Dependencies point `api -> stats -> decider (public API)`.

**Endpoints (FastAPI)**
- `GET /api/stats/decisions?node=&since=`: per node and backend: calls, errors, fallbacks, latency p50/p95/mean,
  mean input/output tokens, mean confidence, plus agreement rate per node.
- `GET /api/decisions?limit=&node=`: recent decision pairs with both backends' picks (feeds the UI trace panel).

**UI:** the trace panel shows both backends' picks per node side by side, with the one the game used highlighted.

**Caveat for fair timing:** Jev latency includes network; Nimble's depends on local GPU load and model warm-up.
Treat single numbers as anecdotes, compare distributions (p50/p95).

## 5. Repository layout

```
gumshoe/
  pyproject.toml
  .env.example           # committed; .env is git-ignored
  .gitignore
  src/gumshoe/
    __init__.py
    config.py            # settings from env
    decider/             # sub-project 1; layers: contract/ backends/ tools/ (+ shadow/ in Plan 1b)
    cases/               # sub-project 2
    mcp_server/          # sub-project 3
    agent/               # sub-project 4
    api/                 # sub-project 4/5
  web/                   # sub-project 5
  tests/
  fixtures/              # captured real API responses
  docs/superpowers/specs|plans/
```

## 6. Sub-project roadmap

1. **Decision layer**, split in two plans:
   - **1a Decision client** (detailed in §7, plan `2026-10-01-decision-layer.md`): config with primary/shadow roles,
     typed models, `SystemOneClient`, factory, CLI `ask`/`compare`.
   - **1b Shadow mode and stats** (§4a; plan written after 1a): `ShadowDecider` (concurrent dual-run, fallback
     rules), SQLite recorder, aggregation queries, FastAPI stats endpoints.
2. **Case engine**: Pydantic case schema (suspects, locations, clues, timeline, culprit, red herrings);
   seeded generator from templates/pools; solvability validator ("every culprit is deducible from clues").
3. **MCP server**: tools such as `list_locations`, `search_scene`, `interrogate`, `check_records`,
   `cross_reference`, `accuse`, `get_notebook`. FastMCP, stdio and in-process modes; inspectable standalone.
4. **Agent loop**: pipeline above, personas, model routing to Ollama, SSE streaming, decision log.
5. **Frontend**: Tailwind (Play CDN) + vanilla JS. Evidence board with SVG strings, chat, live decision-trace panel
   showing both backends per node (primary highlighted), case/seed picker, comparison-stats view fed by
   `/api/stats/decisions`.

Each sub-project gets its own spec → plan → build cycle. Order is fixed by dependencies;
2 and 3 can be swapped.

## 7. Sub-project 1a — Decision client (detailed)

> Updated 2026-10-01: this section describes 1a only. Differences from the first draft: `DECIDER_BACKEND` is replaced
> by `DECIDER_PRIMARY` / `DECIDER_SHADOW`; `decide()` gains a `node` label; the JSONL `LoggedDecider` is dropped
> (logging and stats are Plan 1b, §4a); SQLite replaces JSONL. Where the task table below disagrees with the plan
> file, **the plan file wins**.

### 7.1 Outcome

`python -m gumshoe.decider ...` can send a state and typed questions to either backend and print typed,
probability-bearing answers; every call is logged for later comparison; a `compare` command runs one
request against both backends and prints them side by side.

### 7.2 Components

- **`config.py`**: `Settings` (pydantic-settings) reading `.env`:
  `DECIDER_BACKEND` (`jev`|`nimble`), `JEV_BASE_URL`, `JEV_API_KEY`, `JEV_MODEL`,
  `NIMBLE_BASE_URL` (default `http://localhost:11434`), `NIMBLE_MODEL` (default `nimble`),
  `DECISION_LOG_PATH`, `REQUEST_TIMEOUT_S`. API key is `SecretStr` so it never prints.
- **`decider/models.py`**: Pydantic models for questions (`ChoiceQuestion`, `NoulQuestion`,
  `ScoreQuestion` as a discriminated union on `type`), the request, and parsed answers
  (`ChoiceAnswer`, `NoulAnswer`, `ScoreAnswer`) inside a `DecisionResult`. Shapes come from fixtures (see §3).
- **`decider/base.py`**: `Decider` as a `typing.Protocol`: `async def decide(state, questions) -> DecisionResult`.
- **`decider/client.py`**: `SystemOneClient` using `httpx.AsyncClient`; one class, constructed from a backend profile
  (base URL, model, optional auth header). Both backends use this one class unless Task 1.3 shows a real difference.
- **`decider/factory.py`**: `make_decider(settings) -> Decider` picks the profile from `DECIDER_BACKEND`.
- **`decider/logging.py`**: `LoggedDecider` wraps any `Decider`, measures latency, appends one JSON line per call
  (backend, model, state hash/preview, questions, answers, probabilities, latency_ms, error).
- **`decider/__main__.py`**: small CLI (`ask`, `compare`) using `argparse` or `typer` (decided in Task 1.9).
- **`decider/errors.py`**: `DeciderError` hierarchy (`DeciderConnectionError`, `DeciderAPIError`, `DeciderParseError`).

### 7.3 Data flow

`state` + `[Question]` → `SystemOneClient` builds request JSON → POST → parse JSON into `DecisionResult`
(validation failure ⇒ `DeciderParseError` carrying the raw body) → `LoggedDecider` writes JSONL → caller.

### 7.4 Error handling

- Connection refused / timeout ⇒ `DeciderConnectionError` with backend name and URL (no key in message).
- Non-2xx ⇒ `DeciderAPIError` with status and body excerpt.
- Schema mismatch ⇒ `DeciderParseError` with raw body (so fixtures can be refreshed).
- No retries in v1 (keeps comparison timings honest); a retry policy is deferred.

### 7.5 Testing

- `pytest` + `pytest-asyncio`; HTTP mocked with `httpx.MockTransport` returning captured fixtures.
- Unit tests: model parsing for each question type, factory selection, logger output, error mapping.
- One opt-in integration test (`-m live`) against real Nimble; one against Jev once the key exists.

### 7.6 Task breakdown (each task: goal → steps → concept lesson → checkpoint)

| # | Task | Python concepts taught |
|---|---|---|
| 1.1 | Project setup: `uv init`, Python 3.13, `pyproject.toml`, `src/` layout, `.gitignore`, `.env.example`, pytest runs | virtualenvs, `pyproject`, packages and `src` layout, imports |
| 1.2 | Probe Nimble by hand with `curl`; save request/response fixtures for each question type | HTTP/JSON refresher, reading real API output before modelling it |
| 1.3 | Confirm hosted Jev URL/auth from TypeSafe docs; one `curl` once key is in `.env` | env files, secrets hygiene |
| 1.4 | `config.py` with `Settings` | type hints, `pydantic-settings`, `SecretStr`, `functools.lru_cache` |
| 1.5 | Question models (discriminated union) | Pydantic v2 models, `Literal`, `Annotated`, discriminated unions, validators |
| 1.6 | Answer/result models parsed from fixtures (TDD) | `pytest` basics, fixtures, parametrize, `pathlib`, `json` |
| 1.7 | `Decider` Protocol + `SystemOneClient` | `typing.Protocol` (structural typing), `async`/`await`, `httpx.AsyncClient`, async context managers |
| 1.8 | Error hierarchy + mapping HTTP failures | custom exceptions, `raise ... from`, `try/except` design |
| 1.9 | Factory + `LoggedDecider` (decorator pattern) + JSONL log | composition, `time.perf_counter`, `dataclasses`, file I/O, `logging` vs data logs |
| 1.10 | CLI: `ask` and `compare` (concurrent calls to both backends) | `argparse`/`typer`, `asyncio.run`, `asyncio.gather`, formatted output |
| 1.11 | Live smoke test + short write-up of first Jev vs Nimble observations | pytest markers, reading latency/probability data |

Done criteria: tests pass, `compare` prints both backends for the same request (Jev part runs once the key is set),
log file contains both calls.

## 8. Open items

- Case-file format details and randomisation pools: sub-project 2 spec.
- Ollama role-to-model mapping (which of gemma4 / ministral narrates vs plays suspects): decided in sub-project 4
  by trying both.
- Whether hosted Jev needs any request fields Nimble does not: resolved in Task 1.3.
