# Agent loop (sub-project 4) design

Date: 2026-10-12 (revised after an independent review). Builds on: decision layer (1a/1b), the MCP
server (3). Feeds: the React UI (5).

## 1. Purpose

Turn one line of free text from the player into one game action and, where the action is talk, one
in-character reply. Hosted Jev is the primary decision model and local Nimble the shadow
(`DECIDER_PRIMARY`, `DECIDER_SHADOW`); the shadow's answers are recorded, never used unless the
primary fails. Ollama voices the suspects. The loop is exposed over FastAPI with an SSE stream so
the UI in plan 5 is a pure front end.

Success: with scripted deciders and a scripted LLM, the loop plays whole games (a win and a loss)
through the real MCP tools from free-text turns; every decision lands in the decision log under its
node name and is joinable to its turn event by `decision_id`; no suspect reply that fails
`check_reply` ever appears in any event.

Delivery is three plans, each shippable and reviewed on its own: **4a** the engine, MCP and decider
changes (sections 3.1 and 3.2); **4b** the agent core (`agent/*`, no HTTP); **4c** the API, lifespan,
SSE, settings and the single live run (sections 3.3, 8, 9).

## 2. Decisions taken in brainstorming

| Topic | Decision |
|---|---|
| Turn input | Everything is free text, including the accusation. Jev classifies intent, picks the target and parses accusations. |
| Scope | The loop, a FastAPI turn endpoint with SSE, game and save endpoints, and the small engine/MCP/decider changes in section 3. No terminal CLI. The UI is plan 5. |
| Game access | A real MCP `Client` against `build_server(host)` (the SDK dispatches in-process; no subprocess). The tool list and error codes are the whole contract. A stdio subprocess stays a config switch for later. |
| Pipeline | One batched `understand` call per turn; `parse_accusation` only for accusations; `post_check` only for dialogue. About 1 Jev call per action turn, 2 per dialogue turn. |
| Leak policy | `check_reply` is the hard gate. A flagged draft is redrafted with the violation categories, up to 3 redrafts, then a canned in-character line: `<Name> looks away and says only: "<word>."`, where `<word>` is the first entry of the suspect's `smalltalk_allow` (single neutral words; the template, and a test that it passes `check_reply` for seeds 0-39 and every preset, live in `agent/dialogue.py`). Draft text is never emitted; only the final reply is. |
| `post_check` | Advisory. Recorded for the Jev-vs-Nimble stats and shown in the trace; it never blocks or changes a reply. |
| Accusation parsing | The engine's existing, tested parser (`cases/play/parse.py`) is exposed as MCP tools (section 3.1), not rebuilt in the agent. |
| Irreversible actions | `accuse` and `give_up` both go through a pending-confirm step. |

## 3. Changes outside `agent/`

### 3.1 MCP server: two tools over the existing engine parser

`GameSession.accusation_prompt(text)` and `.interpret(prompt, result)` exist and are tested but are
reachable by no tool, and their types come from `gumshoe.decider`, which the host may not import
(`mcp_server_problems` allows only `gumshoe.cases`). So the wire types are plain views owned by
`cases/play/views.py` (which imports no other gumshoe code), and the decider types stay in the agent:

- `QuestionView(instructions: str, criteria: dict[str, str])` and
  `AccusationQuestions(state: str, questions: dict[str, QuestionView])`, exported from
  `gumshoe.cases`. The agent rebuilds a `ChoiceQuestion` from each `QuestionView`.
- `GameSession.accusation_questions(text) -> AccusationQuestions`: builds the engine prompt,
  stores it on the session (replacing any earlier one), and returns the view. The letter-to-handle
  keys never leave the session.
- `GameSession.interpret_probabilities(probabilities: dict[str, dict[str, float]]) ->
  ParsedAccusation`: applies the engine rule (best option above 0.6 and more than 0.25 ahead of the
  runner-up) to axis -> letter -> probability against the stored prompt, then clears it, and maps
  each pick through `_visible` as `interpret` does. `parse._pick` changes its second parameter from
  `ChoiceAnswer` to `Mapping[str, float]` (a pure refactor; `interpret` passes
  `answer.probabilities`). No stored prompt raises a new engine exception `NoAccusationPrompt`
  (exported from `gumshoe.cases`, mapped by the host to `bad_argument`); an unknown axis, an unknown
  letter or a probability outside [0, 1] is also `bad_argument`.

Host methods and MCP tools: `accusation_questions(game, text)` (text capped at `MAX_TEXT`) and
`interpret_accusation(game, probabilities)`. Both hold the host lock and use the usual `GameError`
codes. A stored prompt is self-consistent (its keys match the questions sent), is replaced by the
next `accusation_questions`, and is dropped with the game; `describe_accusation` and `accuse`
recheck the gate and the repeat rule, so a stale prompt cannot double-spend. The questions name only
nameable candidates (suspects are public), so they carry no spoiler. The agent turns the decider's
`ChoiceAnswer.probabilities` into the `probabilities` argument.

### 3.2 Decider: caller-minted `decision_id`

`ShadowDecider.decide` mints its `decision_id` internally and returns a bare `DecisionResult`, so a
turn event cannot be joined to `/api/decisions`. Add an optional keyword `decision_id: str | None`
to `Decider.decide`; `ShadowDecider` uses it when given (and mints one otherwise) and does not forward it to the
inner per-backend calls; `SystemOneClient` ignores it. Fakes in `tests/decider/fakes.py` and
`tests/stats/test_battery.py` gain the keyword (mypy checks tests). The CLI, compare and battery
only call `decide` and need no change. The agent mints one `uuid4().hex` per decision and puts it on the events that decision
caused. When the primary succeeds the record is written by a background task, so the row may appear a
moment after the event (the UI must tolerate that); fallback and failure records are written inline.

### 3.3 Stats wiring and `create_app`

`create_app(store, *, make_service=None)`: the stats endpoints keep the injected `store` (so
`api/__main__.py` and `tests/api/test_app.py` still work). `make_service` is a factory returning an
async context manager that yields an `AgentService`; tests pass one built from fakes and
`GameHost(ids=SeqIds())`, and the default builds everything from settings. The app's lifespan
enters it. Lifespan and SSE tests use `TestClient` as a context manager (`httpx.ASGITransport` does
not run lifespans). If `make_decider` raises `DeciderConfigError` (no Jev key), the app still starts and serves stats, and
every game endpoint answers 503 `{code: "unavailable"}`; this is tested. The default factory builds the injected `store` (reused as the `Recorder`, never a second store on the same file), `make_decider(...,
recorder)`, the `GameHost`, the MCP `Client` (entered and exited in the lifespan task, because it
owns an anyio task group), and the `AgentService`; on exit it first cancels, then awaits (with a grace period) every turn task the service still
holds, then closes the client, the decider (so records drain) and `OllamaLlm`'s httpx client and calls the
decider's `aclose()` so background records drain.

## 4. Units

New package `src/gumshoe/agent/`, the only unit that sees the decider, the MCP tools and Ollama.
Imports point one way, enforced by `tests/test_architecture.py`:
`api -> agent -> {gumshoe.decider, gumshoe.cases public face, mcp client}`. The agent imports view
types from the public face of `gumshoe.cases` (legal under the existing rules) instead of
mirroring them, and never imports `mcp_server`. The composition root is `api`, which also imports `gumshoe.mcp_server` (`GameHost` is exported;
`build_server` lives in `mcp_server.tools`),
`stats` and `decider`. The agent keeps its own copy of the error codes, with a test that it equals
`mcp_server.errors.CODES`. The architecture tests get an allow-list per package. The agent never
calls `GameHost` methods directly from async code; it goes through the MCP client, whose sync tools
run on a worker thread, so the host's lock never blocks the event loop.

| File | Job |
|---|---|
| `agent/events.py` | `TurnEvent` union (Pydantic, discriminated on `kind`): `intent`, `clarify`, `tool_call`, `tool_result`, `reply`, `post_check`, `confirm`, `cancelled`, `game_over`, `done`. Events caused by a decision carry its `decision_id`. `persona_brief` and `check_reply` calls emit no `tool_call`/`tool_result` event (a `check_reply` call carries the draft); only the final reply's check outcome (ok, categories) appears, on the `reply` event. |
| `agent/game.py` | `GameClient`: a typed wrapper over the MCP `Client`, one method per tool the loop uses (including `reveal` and `close_game`). A tool error becomes `ToolFailure(code, message)`: parsed with the regex in `tests/mcp_server/test_protocol.py`, accepted only if the code is in the agent's copy of the codes; an argument-validation message or a bare `Error executing tool x` becomes code `internal`. |
| `agent/state.py` | Builds the `state` string for Jev from play views and chat memory only. |
| `agent/understand.py` | Builds the `understand` batch, reads the answers into `Intent`. |
| `agent/accuse.py` | Pending-confirm logic and the accusation flow over the tools of 3.1. |
| `agent/dialogue.py` | Persona prompt, Ollama draft, `check_reply`, redraft, canned line, `post_check`. |
| `agent/llm.py` | `Llm` Protocol (`async def complete(model, system, messages) -> str`) and `OllamaLlm` (httpx, `/v1/chat/completions`). |
| `agent/turn.py` | `async def take_turn(ctx: TurnContext, text: str) -> AsyncIterator[TurnEvent]`, the only orchestrator. `TurnContext` is a mutable record `{game, pending, exchanges}` that `take_turn` updates and the service commits in `finally`. An exchange is `(player_text, summary)`: the suspect's reply for dialogue, else a one-line result ("searched the cellar: 2 new facts"). |
| `agent/service.py` | `AgentService`: games, per-game chat memory, pending action and lock; wiring of client, decider, llm. |

### Events

| kind | fields |
|---|---|
| `intent` | `decision_id`, `intent`, `target` (handle or null), `confidence` |
| `clarify` | `reason` (`low_confidence`, `bad_target`, `mismatch`, `accusation`, `pending`, `error`), `text` |
| `tool_call`, `tool_result` | `tool`, `args`; `ok`, `code` (when not ok), `data` (the play view) |
| `reply` | `speaker` (name or null), `text`, `source` (`draft`, `canned`, `help`, `unreachable`), `degraded`, `check_ok`, `violations` (categories only) |
| `post_check` | `decision_id`, `contradicts_says`, `claims_guilt_or_blames_other` (probabilities), `failed` |
| `confirm` | `pending` (`accuse`/`give_up`), `text`, `warnings` |
| `cancelled` | none |
| `game_over` | `outcome` (`won`, `lost`, `gave_up`), `reveal` |
| `done` | none |

`tool_call`/`tool_result` are emitted only for `search`, `interrogate`, `check_records`, `notebook`
(when the player asked), `accuse` and `give_up`. Internal calls emit none: `case_brief`, the
notebook read for `state`, `accusation_questions`, `interpret_accusation`, `describe_accusation`,
`persona_brief`, `check_reply`, `reveal`. The apology is a `clarify` with `reason=error`.

## 5. The turn

0. Before any billed call: the game must exist and be playing (checked with `case_brief`). A turn
   on a finished game yields `game_over` (with the reveal) and `done`, costs no decision, and does
   nothing else.
1. Build `state` (section 6) and call the decider once, node `understand`.
2. Read `intent`, `target`, `weight`, and `confirms_pending` when a pending action exists.
3. Pending state machine. A pending action is `{kind: accuse|give_up, handles?, reasked: bool}`.
   With `confirms_pending` as P(yes): yes is at or above `CONFIRM_GATE`, no is at or below
   `1 - CONFIRM_GATE`. A "confident actionable intent" is an `intent` whose
   `ChoiceAnswer.confidence` is at or above `CONFIDENCE_GATE` and which is not `other`/`meta`.
   Rules, first match wins:
   1. Yes, and the intent is not a confident `accuse`: clear the pending state, then run the action
      (clearing first means a replay can only come back as `repeat`, never double-spend).
   2. No: clear, yield `cancelled`; then, if the intent is confident and actionable, process it in
      this same turn (step 4 on).
   3. Yes together with a confident `accuse` ("yes, but the cook") is ambiguous: treat as grey.
   4. Grey band (including rule 3): if the intent is confident and actionable, drop the pending
      state and process the intent; else if not `reasked`, yield `clarify` ("Still want to ...?")
      with `reason=pending`, set `reasked`, run nothing; else clear the pending state and process
      the turn normally.
   - A failed `understand` leaves the pending state untouched and does not count toward `reasked`.
   - A new `accuse` or `give_up` that resolves replaces the old pending action with a new `confirm`.
4. Otherwise gate: `intent` confidence (`ChoiceAnswer.confidence`, here and for `target`) below `CONFIDENCE_GATE` (0.6, config) yields `clarify`.
   For intents that need a target (`search`, `interrogate`, `talk`, `records`), a `target` below the
   gate, or the `none` option, also yields `clarify`; intents without a target are not gated on it.
5. Intent and target must be compatible: `search` needs a place handle, `interrogate`/`talk` a
   suspect handle, `records` either. A mismatch yields `clarify`; no tool is called.
6. `search`, `interrogate`, `records` (`check_records(subject, kind=None)`, all kinds) and
   `notebook` call their tool and emit `tool_result`. `meta` and `other` get a fixed one-line help
   reply and cost no tool call. `give_up` and `accuse` go to the confirm paths below.
7. Dialogue.
   - `interrogate` calls the tool (which may add facts) and voices the suspect only when the status
     is `ok` or `nothing_new`; `locked` or `unknown` gives a fixed "not reachable yet" reply.
   - `talk` calls no source tool and adds no facts. Reachability comes from the brief's suspect
     `locked` flag (fetched in step 0); a locked suspect gets the same fixed reply. It voices only
     what `persona_brief.says` already holds.
   - Draft: `persona_brief`, Ollama (the dramatic model when the `weight` score is `DRAMATIC_FROM`,
     2.5, or more on its 0-4 scale, else the default model; a draft over `MAX_TEXT` is truncated), `check_reply`, up to 3 redrafts,
     canned fallback, then one advisory `post_check`. `post_check` runs on the final reply only
     (canned lines included) and its state holds the reply, the persona's `says` and the
     notebook contradictions whose lie fact's `speaker` name equals that suspect's name
     (`ContradictionView` has only fact handles and text; `NotebookFact.speaker` and
     `PersonaBrief.name` both come from the engine's `_suspect_name`).
8. `accuse` flow: `accusation_questions`, one decision (node `parse_accusation`) whose answers
   become the `probabilities` for `interpret_accusation`, then `describe_accusation`.
   - Missing or not-yet-allowed parts: `clarify` naming them. `repeat=true`: `clarify` saying that
     triple was already tried.
   - Resolved and `can_confirm`: only now set the pending action (storing the resolved handles) and
     yield `confirm` with the plan's confirmation line and warnings. On a yes, `accuse(confirmed=
     true)` runs with the stored handles (not a re-parse). If it comes back `not_permitted`,
     `repeat` or `needs_confirmation`, the loop yields `clarify` instead.
   - After `accuse`: a wrong answer with attempts left yields a `tool_result` carrying the number
     of correct parts and the attempts left; a win or the last miss ends the game (step 9).
   - `give_up` yields `confirm` ("Give up and see the answer?") and sets a pending action; on a
     yes it calls `give_up`, which already returns the reveal.
9. End of game (win, last miss, `give_up`): the reveal (from `give_up`'s result, else a `reveal`
   call) goes in `game_over`, then `done`. The service keeps the game until `DELETE` so the UI can
   still show the notebook. On later turns step 0 calls `reveal` again for the `game_over` event.

Every path ends with `done`. No path raises out of `take_turn`: a failure becomes an event.

## 6. What Jev sees

`state` is plain text rebuilt each turn from play views only (brief, notebook, locked flags). The
player's message comes first (only the first 200 characters are stored as `state_preview`), then
the pending confirmation line if any, the last two exchanges from chat memory, and the places and
suspects. The notebook is capped deterministically, with no history needed: every contradicted fact plus
the last 30 facts in notebook order (sections sort by source label, so the same sources are always
cut first; accepted and documented) (standard holds up to 39 facts and long 53). It never contains anything from
`reveal`, the case bytes or an unearned fact, so a Jev prompt cannot leak the answer.

Questions in the `understand` batch:

| Name | Type | Content |
|---|---|---|
| `intent` | choice | `search`, `interrogate`, `records`, `talk`, `accuse`, `notebook`, `give_up`, `meta`, `other`, each with a "pick when" description |
| `target` | choice | one option per place and suspect plus `none`; keys are `place_N` and `suspect_N` from the views' `number`, mapped to handles agent-side (readable in traces; the build raises if a pack ever exceeds 26 options, castle long is 13 plus `none`) |
| `weight` | score | dramatic weight, 5 levels (0-4) |
| `confirms_pending` | noul | only when a pending action exists |

`parse_accusation` uses the questions returned by the tool of 3.1, unchanged. `post_check` has two
noul questions judgeable from text alone: `contradicts_says` (the reply conflicts with the persona's
`says` list) and `claims_guilt_or_blames_other` (the reply confesses, or accuses another suspect).
The persona prompt and `post_check` also get the notebook contradictions that involve that speaker.

Nodes in the decision log are exactly `understand`, `parse_accusation`, `post_check`. Nimble runs on
the same Ollama as persona drafts, so shadow calls contend with drafts for the GPU; this affects
latency and cold-flag statistics and is documented, not worked around.

## 7. Failure rules

Catch `DeciderError` (not only `DeciderAllFailedError`): with no shadow configured, a primary
failure surfaces as the raw error.

| Failure | Behaviour |
|---|---|
| `understand` fails (any `DeciderError`) | `clarify` with a fixed apology; no tool was called; not stored in chat memory. |
| `parse_accusation` fails | `clarify` with the apology; nothing spent; the pending state is untouched. |
| `post_check` fails | Ignored; the approved reply stands; the event is `post_check` with `ok=false`. |
| A tool already changed state (e.g. `interrogate` added facts) and a later stage fails | The tool result and reply already sent stand; chat memory records the exchange. Nothing is rolled back. |
| Primary fails, shadow answers | Existing fallback in `ShadowDecider`; recorded as a fallback. |
| Ollama unreachable or times out | The canned line, with `degraded=true` on the `reply` event. |
| MCP `ToolFailure` | A `tool_result` event with `ok=false` and the code. `game_over` goes to the end-of-game path; `unknown_game` ends the stream with `done`; `internal` is logged to stderr and reported as the apology. |
| Accusation axis unclear | `clarify` names the missing axes. A handle is never guessed. |
| Unexpected exception in a stage | Logged to stderr, the turn yields the apology and `done`. No traceback or case detail crosses the wire. |
| Client disconnects mid-turn | The turn runs to completion regardless (section 8): host mutations, chat memory and the pending state are all written. |
| `Llm` raises `LlmError` (unreachable, timed out, bad response) | Same as Ollama unreachable: the canned line with `degraded=true`. |

## 8. API

Added to `create_app`; the stats endpoints stay as they are.

- `POST /api/games` `{seed, preset?}` returns `{game, brief}`.
- `POST /api/games/{id}/turn` `{text}` (1 to 1000 characters) streams SSE: `event: <kind>` plus one
  JSON `data:` line per `TurnEvent`, ending with `event: done`. A plain `StreamingResponse`; no new
  dependency. The game's existence is checked before the response starts, so an unknown game is a
  real 404. A turn runs in a detached `asyncio.Task` that the service keeps a strong reference to: the task
  takes the per-game `asyncio.Lock` (a second turn waits there, before any event), runs
  `take_turn` to completion, writes chat memory and the pending state in a `finally` (only while the game is still registered, so a `DELETE` is never undone), and pushes
  events to a queue. The SSE generator only drains the queue, so a disconnect cancels the reading,
  never the turn.
- `GET /api/games/{id}` returns the brief and the notebook.
- `POST /api/games/{id}/save` and `POST /api/games/load` `{name}` wrap `save_game` and `load_game`
  (the save holds the game, not the chat or the pending action).
- `DELETE /api/games/{id}` takes the game's lock first (so a running turn is never orphaned), then
  wraps `close_game` and frees the chat memory and the lock. Without it
  the open-game cap would become permanent.
- The 1-1000 character check on `text` is FastAPI's own validation, so that 422 body is `{detail}`
  rather than `{code, message}`.
- Errors map from the agent's `ToolFailure.code` (a `GameError` code, or `internal`) to a status with
  `{code, message}` as the body: `unknown_game` 404, `bad_argument`, `unknown_handle` and `bad_save`
  on a load 422, `bad_save` on a save write and `internal` 500, `too_many_games` 429, others 409.

The chat memory (last two exchanges per game) and the pending action live in `AgentService` and end
with the process.

## 9. Configuration

New settings: `OLLAMA_BASE_URL` (default `http://localhost:11434/v1`), `PERSONA_MODEL_DEFAULT`
(`ministral-3:14b`), `PERSONA_MODEL_DRAMATIC` (`gemma4:12b`), `DRAMATIC_FROM` (2.5), `CONFIDENCE_GATE` (0.6),
`CONFIRM_GATE` (0.8, validated to lie in (0.5, 1] so the yes and no bands cannot overlap), `MAX_REDRAFTS` (3), `LLM_TIMEOUT_S` (60). `gemma4:12b` is the dramatic model by choice (the stronger writer here); both are config. All validated like the existing `Settings`.

## 10. Testing

All tests run on fakes against the real in-process MCP server and a real `GameHost` with
`ids=SeqIds()` (pinned handles). The scripted decider is wrapped as
`ShadowDecider(ScriptedDecider, ScriptedShadow, FakeRecorder)` and drained before asserting, so
decision-log rows and `decision_id` joins are really checked.

- A whole game won and one lost through free-text turns.
- Each intent maps to its tool; `meta` and `other` call no tool; every intent/target mismatch
  clarifies without a tool call.
- Clarify paths: low intent confidence, `none` target, no target needed (a notebook request is not
  gated), unclear accusation axis, accusation not yet allowed, repeated triple.
- Pending flow, for both `accuse` and `give_up`: yes at 0.8, yes in the grey band (re-ask), no,
  another intent in between, "yes, but the cook" (yes wins), pending line present in `state`.
- A wrong accusation with attempts left; a win; the last miss; `game_over` carries the reveal once per game end (via `give_up`'s result when giving up).
- Dialogue gating: `locked` and `unknown` statuses give the fixed reply and no draft.
- Leak path: a draft naming an unearned method or motive (a distinctive candidate label) is redrafted; three bad drafts give the canned line;
  no event contains any draft text; the canned line passes `check_reply` for every seed and preset.
- Every failure row of section 7, one test each, including no shadow configured.
- Leak property across seeded random scripted games, asserted on every event except `game_over`
  (which carries the reveal): no raw ids or truth fields, no unfound secret, and no full true
  triple as a unit outside the events that echo the player's own accusation (`confirm`, an
  accusation `clarify`, the accusation `tool_result`). Suspect names are public. The scripted Llm
  draws its drafts only from its prompt plus adversarial candidate labels; the agent adds no guard
  against unheld fact text because `check_reply` allows tokens of a suspect's still-available facts.
- MCP additions: the two new tools (including no stored prompt, an axis with fewer than two
  options, and the new tools in the every-tool leak checks and the exact `TOOLS` set in
  `tests/mcp_server/test_protocol.py`), and `Decider.decide(decision_id=...)` for `ShadowDecider` and the plain client.
- API: SSE parsed back and compared to the event list; a second concurrent turn waits (tested at the service level with asyncio; `TestClient.stream` is used only for SSE parsing and the lifespan, because `httpx.ASGITransport` buffers bodies and skips lifespans); unknown game
  is 404 before streaming; lifespan start and shutdown; `DELETE`.
- Architecture: the import rules of section 4.
- One opt-in `-m live` test: about five turns against real Jev and Ollama, run once at the end
  (hosted Jev is billed per call).

## 11. Non-goals

- The React UI, the trace panel and the stats view (plan 5).
- A "contradicted" signal in `PersonaBrief` itself (the notebook's contradictions are used instead).
- Chat persistence, multiple server processes, auth, rate limits.
- Streaming Ollama tokens (a reply is one event).
- Packs other than castle.

## 12. Open items for the plan

- Prompts and templates the plan writes in full: the `understand` state template and section order;
  the persona system prompt; the redraft instruction; the `post_check` state template; the field
  names and types of `Intent`; the `Llm.complete` message type; the `make_service` factory arguments.

- Exact wording of the `intent` descriptions and the fixed apology, help and not-reachable lines:
  written in the plan, tuned only after the single live run.
- The `Decider.decide` signature change touches `ShadowDecider`, `SystemOneClient` and the test
  fakes; the plan makes it its own first task.
- Carried from the 4a final review into 4b: run `accusation_questions` and `interpret_accusation` for
  one parse under the per-game lock (nothing ties an interpret call to its questions); map a
  `bad_argument` from `interpret_accusation` to the parse_accusation apology `clarify`, not a
  `tool_result` failure; a returned `AccusationQuestions` view is stale once a newer call replaces
  the stored prompt.
- Refinement made in 4b (code is right, this note updates the spec): a yes while an accusation is pending is also not run when the confident intent is `give_up` (rule 3 of the pending state machine blocks a yes together with a confident `accuse`, or with a confident `give_up` unless the pending action is `give_up`). `GameClient` still lacks save/load (4c adds them). `TurnContext` is passed live and mutated in place.
