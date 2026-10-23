# Gumshoe API contract (for the React UI)

Written from the code after plan 4d-2 (tasks 1-12). Interactive docs for the plain JSON routes are at
`/docs`; the server-sent event streams are described here only.

## 1. Conventions

- All request and response bodies are JSON (except the event streams, section 4). Unknown request
  fields are refused with 422 `bad_request`. Every API route starts with `/api` (the generated `/docs`, `/redoc` and `/openapi.json` do not).
- No authentication. Bind to the loopback address only.
- **Errors** always have this shape, whatever raised them:

  ```json
  {"code": "unknown_game", "message": "no such game"}
  ```

  `message` is for people and never echoes the player's text or any secret. Match on `code`.

| code | status | when |
|---|---|---|
| `unknown_game` | 404 | no open game has that id (also after a server restart) |
| `bad_argument` | 422 | the game engine refused an argument (for example an unknown preset) |
| `unknown_handle` | 422 | a handle the player's case does not have |
| `bad_save` | 422 | a save name that is missing, someone else's, malformed or unreadable (message "that save cannot be read"); 500 when writing the save failed |
| `bad_request` | 422 | the body, query or path did not validate (message says where and what, never the input); also `ids` of the wrong size, and HTTP 400 |
| `too_many_games` | 429 | the engine's game cap is reached (`MAX_GAMES`: 1000 locally, 200 in public mode); delete one first |
| `rate_limited` | 429 | a request, new-session, game-creation or turn rate is exceeded; carries `Retry-After` (section 6a) |
| `quota` | 429 | too many games open, or too many saves, for this session or IP; finish or delete one (no `Retry-After`, no counts in the message) |
| `cold` | 410 | the game was closed after sitting idle (`GAME_IDLE_MINUTES`); message "That case went cold. Start a new game." Owner only: anyone else gets the same 404 `unknown_game` as for a missing game |
| `busy` | 429 | too many turns running for the IP, or the turn queue is full; carries `Retry-After: 5` |
| `turn_in_progress` | 409 | a turn or confirm button press is still running for this game |
| `no_such_pending` | 409 | `POST /confirm` with an id that is not the confirmation waiting |
| `game_over` | 409 | the action needs a game still being played |
| `not_over` | 409 | the reveal was asked for before the game ended |
| `state_mismatch` | 409 | the engine's state does not match the request; any new engine code also maps to 409 |
| `not_found` | 404 | no such route |
| `not_recorded_yet` | 404 | `GET /api/decisions/{id}` before that decision is written: retry |
| `method_not_allowed` | 405 | wrong HTTP method for a route |
| `too_large` | 413 | request body over the cap |
| `unavailable` | 503 | the game endpoints are off (see `GET /api/health`) |
| `internal` | 500 | anything unexpected; the body never carries the cause |

  An HTTP error with no code of its own comes back as `http_error`.
- **Body cap**: `MAX_BODY_BYTES` (default 16384). A body over it gets 413 `too_large`, by
  `Content-Length` before reading, or while reading a chunked body.
- **CORS**: off unless `CORS_ORIGINS` (comma-separated exact origins such as
  `http://localhost:5173`, never `*`) is set. Allowed methods GET, POST, DELETE; allowed header
  `content-type`. 413 answers carry the CORS headers too. In development the Vite dev server proxies
  `/api`, so none is needed.

- **Cross-origin caveats**: a 500 answer and a rejected CORS preflight carry no CORS headers and no
  `{code, message}` body (a disallowed preflight is a plain-text 400 from Starlette), so a cross-origin UI sees
  them as network errors. The Vite dev proxy avoids this.

## 2. Server

### `GET /api/health` -> `Health`

```json
{"status": "ok", "game": "on", "reason": null, "primary": "jev", "shadow": "nimble",
 "persona_models": {"default": "ministral-3:14b", "dramatic": "gemma4:12b"}, "personas": "up"}
```

- `status` is always `"ok"` (the process is up).
- `game` is `"on"` or `"off"`. When `"off"`, every game route answers 503 `unavailable` and `reason`
  says why (for example the decider is not configured, or "the server has not finished starting").
  The stats routes still work.
- `personas` is `"up"` or `"down"`: whether the persona model server answers (probed with a 1 s timeout,
  cached 5 s). When `"down"` the game still runs but suspects only give stock lines.
- `primary`, `shadow` (may be null), model names only: never a key or a URL.

### `GET /api/meta` -> `Meta`

`{presets: string[], default_preset: string, max_attempts: int, max_turn_chars: int}`.
`default_preset` is `"standard"`, `max_attempts` is 3, `max_turn_chars` is 1000.

## 3. Games

A game id (`game`) is an opaque string. Games live in memory: a server restart ends them (save the
ones to keep). No route ever returns a seed.

### `POST /api/games`

Body `{seed: int, preset?: string}` (`preset` default `"standard"`, at most 32 chars; `seed` is a strict
integer: a string, float or boolean fails validation with 422 `bad_request`; an integer outside 0 to 2^63-1 is 422
`bad_argument`; a preset the pack cannot host is 422 `bad_argument` too). Answer 200 `GameCreated`:

```json
{"game": "<id>", "brief": PlayerCaseView, "preset": "standard"}
```

`PlayerCaseView`: `{intro, locations[], suspects[], record_kinds[], attempts_left, status}`.
`locations[]` and `suspects[]` items: `{number, handle, name, description, locked}`;
`record_kinds[]` items: `{key, label}`; `status` is `playing | won | lost`.

### `GET /api/games` -> `GameSummary[]`

The open games of your session, oldest first (`[]` without a session): `{game, preset | null, outcome, attempts_left, turn_running}`.
`outcome` is `playing | won | lost | gave_up`. `turn_running` is true while a turn runs (section 6).

### `GET /api/games/{game}` -> `GameState`

Everything needed to redraw a game after a reload:

```json
{"brief": PlayerCaseView, "notebook": NotebookView, "outcome": "playing",
 "pending": {"pending_id": "...", "kind": "accuse", "text": "...", "warnings": ["..."]} | null,
 "reveal": {"culprit", "method", "motive", "secret"} | null,
 "preset": "standard" | null}
```

- `notebook`: `{sections[{source, facts[{handle, text, speaker|null, relates_to[], contradicted}]}],
  contradictions[{lie, exposer, text}]}`.
- `pending` is the confirmation waiting for an answer (`kind` is `accuse` or `give_up`), or null.
- `reveal` is present only once the game is over (outcome not `playing`).
- `preset` is null for a loaded game (a load does not say).
- `gave_up` stays `gave_up` (the engine alone would say `lost`), except after a load: a game that was given up
  before being saved reads `lost`, because the save does not record it.

### `POST /api/games/{game}/turn`

Body `{text: string (1-1000 chars), pending_id?: string (1-64 chars)}`. Answers 200
`text/event-stream` (section 4). Before streaming starts it can fail (as a plain JSON error):
404 `unknown_game`, 409 `turn_in_progress`, 422 `bad_request`, 429 `rate_limited` / `busy`, 503 `unavailable`.
Send `pending_id` when a confirmation is on screen (section 5).

### `POST /api/games/{game}/confirm`

Body `{pending_id: string (1-64), answer: "yes" | "no"}`. The confirm and cancel buttons: no decision
model is involved. Answers the same event stream as a turn. Errors before streaming: as for a turn,
plus 409 `no_such_pending` when that id is not the confirmation waiting.

### `GET /api/games/{game}/turns` -> `TurnRecord[]`

The transcript for a reloaded page: at most the last 200 turns, oldest first.

```json
{"turn_id": "<hex>", "kind": "turn" | "confirm", "text": "...", "ts": "2026-10-13T10:00:00.000+00:00",
 "events": [<events as in section 4>], "complete": true}
```

`text` is what the player typed, or `yes`/`no` for a button. `complete` is false for a turn still
running (its `events` so far, last in the list). Only turns that really ran are kept.

### `POST /api/games/{game}/save` -> `{name: string}`

Waits for a running turn first, then saves. 404 `unknown_game`; 410 `cold`; 429 `quota` when the session
or IP already holds its cap of saves (`SESSION_SAVES`, `IP_SAVES`; checked before anything is written); 500 `bad_save` if the write failed.
Known quirk: when the saves folder is full (the host's cap) the host also raises `bad_save`, which this API maps
to 500, so a client cannot tell a full folder from a failed write.

### `POST /api/games/load`

Body `{name: string (1-64)}`. Answer 200 `GameCreated` with a NEW game id and new handles, and
`preset: null`. Errors:

- 422 `bad_argument`: the name is not 16 lowercase hex characters.
- 422 `bad_save`: the save is missing or unreadable (also one that holds no sound case, is from another
  version, or names a pack this server lacks).
- 409 `state_mismatch`: the save's progress belongs to another case.
- 429 `too_many_games`.

### `DELETE /api/games/{game}` -> 204

No body. Waits for a running turn. 404 `unknown_game`; 410 `cold` for the owner of a game that went idle.

An idle game (no request for `GAME_IDLE_MINUTES`, default 30) is closed by the server and its id then
answers 410 `cold` to its owner, and 404 `unknown_game` to everyone else. A turn in flight keeps the
game alive. The 410 note is remembered for a limited time only; after that the id reads as missing.

### `GET /api/saves` -> `SaveSummary[]`

Only your own saves, newest first (`[]` without a session): `{name, created_at (UTC ISO 8601), pack, status: playing | won | lost}`. Never the case.
An empty list when the server has no saves folder wired. Saves older than `SAVE_RETENTION_DAYS`
(default 30; 0 = keep forever) are deleted by the server.

### `DELETE /api/saves/{name}` -> 204

Deletes one of your own saves; no body. A save that is someone else's, missing or malformed gives the same
422 `bad_save` ("that save cannot be read"), so a name tells a stranger nothing.

## Sessions

`POST /api/games` and `POST /api/games/load` issue a signed session cookie (`gs_session`, or
`__Host-gs_session` in public mode); the browser sends it automatically. A game or save belongs to
the session that made it. A game that is missing and a game that is not yours both give the same
404 `unknown_game`. `GET /api/games` and `GET /api/saves` return only your own, and `[]` without a
session. A write whose `Origin` is not the site's own gets 403 `forbidden`; a write with a
non-JSON body gets 415.

## 4. The event stream

Both `POST .../turn` and `POST .../confirm` answer `200 text/event-stream` (headers
`Cache-Control: no-cache`, `X-Accel-Buffering: no`). Read it with `fetch` and a stream reader (not
`EventSource`, which cannot POST).

- Each event is one block of two lines and a blank line:

  ```
  event: reply
  data: {"kind":"reply","speaker":"Mr Grey", ...}

  ```

  The `data` is one line of JSON and always contains `kind`, equal to the `event:` name.
- While a turn is quiet, the server sends a comment line `: ping` followed by a blank line every
  15 seconds. Ignore comments.
- The stream ends with `done` for any turn that runs. Exceptions: a game deleted while the turn waited for its
  lock ends with just `done` (no `clarify`); a client that leaves while its turn waits gets nothing (the turn
  is not run); a turn cancelled by shutdown before its first step ends with an empty stream (no events at all,
  not even `done`; `test_aclose_right_after_start_turn_still_ends_the_stream` pins that the stream ends and is
  empty). Even when the server is shutting down mid-turn the stream ends
  with `clarify` (`reason: "error"`, text "The game server is shutting down. Please try again in a
  moment.") and then `done`. If the connection drops without a `done`, the turn did not finish
  normally for you: reload with `GET /api/games/{game}` and `/turns`.
- A client that leaves does not stop the turn: it runs on and is kept in the transcript.
- Failures inside a turn arrive as events (`tool_result` with `ok: false`, `clarify`), not as HTTP
  errors, because the HTTP status is already 200.

| event (`kind`) | fields |
|---|---|
| `intent` | `decision_id: string`, `intent: string`, `target: string \| null`, `confidence: number` |
| `clarify` | `reason: low_confidence \| bad_target \| mismatch \| accusation \| pending \| error`, `text: string`, `decision_id: string \| null`, `problems: Problem[]` |
| `tool_call` | `tool: string`, `args: object` |
| `tool_result` | `tool: string`, `ok: bool`, `code: string \| null`, `message: string \| null`, `data: object \| null` |
| `reply` | `speaker: string \| null`, `text: string`, `source: draft \| canned \| help \| unreachable`, `degraded: bool`, `violations: string[]`, `model: string \| null`, `drafts: int`, `latency_ms: number \| null` |
| `post_check` | `decision_id: string`, `contradicts_says: number \| null`, `claims_guilt_or_blames_other: number \| null`, `failed: bool` |
| `confirm` | `pending: accuse \| give_up`, `pending_id: string`, `text: string`, `warnings: string[]`, `decision_id: string \| null` |
| `cancelled` | (none) |
| `game_over` | `outcome: won \| lost \| gave_up`, `reveal: {culprit, method, motive, secret}` |
| `queued` | `position: int` (1 = next in line) |
| `done` | `turn_ms: number \| null` |

Notes:

- `clarify.problems` is filled for `reason: "accusation"`, empty otherwise. Each problem:
  `{axis: who | how | why, reason: unclear | not_permitted, options: [{handle, name}]}`. The options are
  what may be named right now: use them as pickers. `clarify.decision_id` is the accusation-parsing
  decision for accusation clarifies. `reason: "pending"` means the message was about a confirmation: either
  "still want to go ahead?" (the confirmation is kept) or "nothing is waiting" (see section 5).
- `reply.model` is the persona model asked (draft and canned replies), `drafts` the number of persona
  model calls made, `latency_ms` the time spent drafting, checks included. `degraded` is true when the
  reply fell back to a safe one; `violations` lists check categories only.
- `reply.source`: `draft` (the persona model), `canned` (a safe stock line), `help` (the help text),
  `unreachable` (the suspect asked about is not available yet: still locked).
- `confirm.decision_id` is the accusation-parsing decision (accuse only).
- `done.turn_ms` is the wall time of the whole turn.
- Every `decision_id` can be looked up with `GET /api/decisions/{id}` (section 7). The primary's
  record can land a moment after the event: 404 `not_recorded_yet`, retry.

## 5. Confirmations

1. An accusation or a give-up is not run at once. The turn ends with a `confirm` event
   (`pending`, `pending_id`, `text`, `warnings`) and then `done`. The game holds that one confirmation.
2. To say yes, either:
   - send `POST /api/games/{game}/confirm` `{pending_id, answer: "yes"}`, or
   - type the yes in a normal turn and send `pending_id` in the body. A typed yes runs the action only
     when it carries the id of the waiting confirmation. Without it (or with an old id), the
     confirmation is shown again (a `confirm` event) and nothing runs.
   - While a confirmation waits, a yes that is unclear or below the confidence band is not run and not dropped:
     the turn sends `clarify` with `reason: "pending"` ("Still want to go ahead? ...") and keeps the
     confirmation. This is done once; a second unclear reply drops it (`cancelled`, then the message is handled
     normally).
   - `POST /confirm` with an id that passed the 409 pre-check but is no longer the waiting one when the turn
     runs (a rare race) sends `clarify` with `reason: "pending"` and the text "There is
     nothing waiting for your confirmation right now."
   - A typed yes that carries a `pending_id` when nothing is pending takes the stale-yes path: if the text is
     not itself an actionable request, the answer is a `reply` (`source: "help"`) saying nothing is waiting, plus
     the help text; otherwise it is handled as a normal request.
3. `answer: "no"` (button) or a typed no ends the confirmation with `cancelled`.
4. A new request that is not an answer (a different action) drops the confirmation, with a
   `cancelled` event first.
5. A reloaded page reads the waiting confirmation from `GET /api/games/{game}` (`pending`) and can
   answer it with the same id.
6. An accusation that is carried out ends with `game_over` (won, lost) and the reveal; a confirmed
   give-up ends with `game_over` with `outcome: "gave_up"`.

## 6. One turn at a time

A game runs one turn at a time (each turn is billed, so they are never queued). While a turn or a
button press is running, a second `turn` or `confirm` for that game is refused at once with 409
`turn_in_progress` (as a JSON error, no stream). The next may start once the stream's `done` has
arrived. `GameSummary.turn_running` says whether a turn is running, for a second tab.
Save and delete wait for the running turn instead of being refused. Different games do not block
each other.

## 6a. Limits

Every limit is a setting (`.env.example`); `0` = unlimited.

- **429 with `Retry-After`** (whole seconds, also in the JSON error): `rate_limited` (a rate was
  exceeded: requests per IP, new sessions per IP, games created per session, turns per session or
  IP) and `busy` (retry after 5). `quota` (too many games open for the session or IP) is a 429 too.
  The body is the usual `{code, message}`. Save `quota` (`SESSION_SAVES`, `IP_SAVES`) has no
  `Retry-After` and no counts: delete a save and try again.
- **Housekeeping**: a background loop closes idle games every 60 s (`GAME_IDLE_MINUTES`), and purges
  saves older than `SAVE_RETENTION_DAYS` hourly and once at startup. `0` turns each off (idle expiry,
  purge) or lifts the cap (`SESSION_SAVES`, `IP_SAVES`).
- **`GET /api/health` counts** against the per-IP request budget like any other API request.
- **The new-session quota counts attempts**, not only sessions that were created.
- **A full limiter table fails closed**: each table keeps at most `LIMITER_MAX_KEYS` keys and only
  evicts expired ones; when every key is live, a new client gets 429 until entries expire.
- **The `queued` event**: when the turn gate (`MAX_PARALLEL_TURNS`) is full and the turn is allowed
  to wait (`TURN_QUEUE_SIZE`), the stream starts with `event: queued`, `data: {"kind":"queued",
  "position":N}` (approximate, 1 = next). The turn then runs as usual. A turn that is waiting for
  a place or for its game's lock still counts in the queue, but holds no running place.
- **The busy ending**: if no place frees within `TURN_QUEUE_WAIT_S`, the stream ends with a `clarify`
  (`reason: "error"`, text "The detectives are busy right now. Please try again in a moment.") and
  `done`. The turn did not run and cost nothing; send it again later.
- **409 `turn_in_progress`** is also what a second turn from the same session gets while one of its
  turns runs (`SESSION_TURNS_IN_FLIGHT`, default 1), even in another game.

## 7. Stats

### `GET /api/stats/decisions` -> `StatsReport`

Query: `node` (a decision node name), `since` (ISO 8601 datetime), `include_cold` (bool, default false;
it changes latency samples only). Answer:

```json
{"generated_at": "...", "since": null, "include_cold": false, "nodes": [NodeStats]}
```

`NodeStats`: `{node, decisions, fallbacks, compared, shadow_errors, question_agreement: {question: rate},
intent_confusion: {primary_intent: {shadow_intent: count}}, agreement_rate | null, backends:
[BackendStats]}`. Lead a comparison view with `question_agreement` (per question): the pooled
`agreement_rate` is dominated by the questions asked most. `intent_confusion` is filled for nodes that
ask for an intent; its shadow-side key `"(error)"` counts decisions the shadow failed to answer.
`shadow_errors` counts those decisions (a fallback is not one); they are not in `compared`, so
agreement covers only the decisions both answered in time. `score_offset: {question: mean(shadow -
primary)}` shows a constant bias between the backends. Yes/no questions agree by band (yes / unsure /
no at the confirm gate); `weight` agrees when both scores sit on the same side of `dramatic_from`
(2.5), the one threshold the game acts on. `role` is `primary` or `shadow`, the role the backend
mostly played on that node.

`BackendStats`: `{backend, role, calls, errors, cold_calls, used_calls, latency_ms: {p50, p95, mean},
error_latency_ms: {p50, p95, mean}, mean_input_tokens, mean_output_tokens, total_input_tokens,
total_output_tokens, est_cost_usd, mean_confidence}`. Latency figures and means may be null. Failed
calls (timeouts) are in `error_latency_ms`, so a slow failing backend does not look fast.
`est_cost_usd` comes from the `*_USD_PER_MTOK_*` settings and is 0 when none are set.

### `GET /api/decisions` -> `DecisionView[]`

Query: `limit` (1-200, default 20), `node`, `ids` (comma-separated decision ids, 1 to 200; then exactly
those and `limit` does not apply; otherwise 422 `bad_request`), `disagree` (`true` keeps only
head-to-heads where the backends differ). Newest first.

### `GET /api/decisions/{id}` -> `DecisionView`

404 `not_recorded_yet` until the decision is written: retry after a moment.

`DecisionView`: `{decision_id, node, ts, fallback, state_preview, calls: [CallView],
agrees: {question: bool}}` (`agrees` is empty unless the decision is a fair head-to-head);
`CallView`: `{backend, role, used, cold, latency_ms, error | null, input_tokens | null,
output_tokens | null, est_cost_usd | null, answers: {question: {verdict, confidence}}}`.

## 8. Not provided

Out of scope of plan 4d-2: per-game stats, autosave, per-source "exhausted" flags, static file
serving (the UI is served by its own dev server or host), and time series of the stats.
