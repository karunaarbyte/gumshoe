# Public hardening (stage 4) design

Date: 2026-10-16. Status: draft for the owner's review. Follows `docs/superpowers/roadmap-after-5.md` (stage 4) and
the API contract `2026-10-13-api-contract.md`.

## 1. Purpose and decisions

Today the API binds to loopback, has no authentication, and every cap is global (1000 games, 500 saves). Anyone who
can reach it can read, replay or delete any game, fill the shared caps, spend Jev, and read every player's typed
text on the stats page. This stage makes it safe to run as a **public site** on the owner's machine, behind a tunnel.

Decisions taken with the owner (2026-10-16):

| Topic | Decision |
|---|---|
| Audience | Long-lived public site, but this spec covers only the safety layer (A), idle expiry (B-lite) and exposure (C-lite) |
| Hosting | The API and Ollama run on the owner's machine; TLS ends at a tunnel (e.g. Cloudflare Tunnel). Persona models stay local |
| Identity | Anonymous signed session in an HttpOnly cookie; no accounts |
| Budget cutoff | When the daily Jev cap is reached the game falls back to Nimble alone ("slow mode"), it does not close |
| Admin | `ADMIN_TOKEN` in `.env`, sent as `Authorization: Bearer`. Unset means the admin endpoints do not exist (404) |
| Out of scope | Accounts, leaderboards, cross-device saves, games surviving a restart, CAPTCHA, WAF, multi-instance deployment |

Success: a stranger can play a full game; cannot read or affect another player's game, save or text; cannot spend
more Jev than the daily cap; cannot lock others out of the global caps by themselves; and the owner can still use the
stats page and read disagreements.

## 2. Sessions and ownership

- **Cookie.** `gs_session = <id>.<sig>`: `id` is 128 random bits (url-safe), `sig` is HMAC-SHA256 of `id` with
  `SESSION_SECRET`. Attributes: `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age` 30 days, `Secure` when the request
  arrived over HTTPS (known from `X-Forwarded-Proto` when `TRUST_PROXY=true`, else the scheme).
- **Issue.** A request with no valid cookie gets a fresh session and the `Set-Cookie` header on its response. A bad
  signature is treated as no cookie (never an error). Comparison uses `hmac.compare_digest`.
- **Secret.** `SESSION_SECRET` (at least 32 chars). If unset, the server generates one at start and logs a warning:
  sessions then reset on restart. Rotating the secret signs everyone out; games are lost on restart anyway.
- **Ownership.** `_Slot` in `api/service.py` gains `owner: str` (the session id). Every `/api/games/{game}/...` route
  takes the session as a dependency and calls one `service.slot_for(game, session)`; a game that does not exist and a
  game owned by someone else are **indistinguishable**: both raise `unknown_game` (404) with the same message, and
  the check happens before any lock, turn or save is touched.
- **Listing.** `GET /api/games` returns only the caller's games.
- **Saves.** Save files are named by the host and survive restarts. The service records the owner beside each save
  (a sidecar `<name>.owner` file holding a keyed hash of the session id, written at save time). `GET /api/saves`
  lists only the caller's saves; `POST /api/games/load` of a save the caller does not own raises the same
  `bad_save` error as a missing one. Saves without a sidecar (made before this change) are visible to nobody; the
  owner can delete or adopt them from the shell.
- **CSRF.** Every `POST`/`DELETE` must carry an `Origin` (or, failing that, `Referer`) whose host equals the request
  `Host` (or the forwarded host under `TRUST_PROXY`). Otherwise `403 forbidden`. `GET` never changes state. Requests
  with a body must use `application/json`.

## 3. Limits

All numbers are settings with these defaults (0 = unlimited, for the owner's local testing).

| Limit | Default | Scope | Answer |
|---|---|---|---|
| Games open at once | 3 | session | `429 quota` |
| Games created per hour | 20 | session | `429 rate_limited` |
| Saves held | 10 | session | `429 quota` |
| Turns per minute | 30 | session | `429 rate_limited` |
| Turn in flight | 1 | game (exists) | `409` as today |
| New sessions per hour | 10 | client IP | `429 rate_limited` |
| Requests per minute | 300 | client IP | `429 rate_limited` |
| Games open / saves held | 1000 / 500 | global | as today |
| Turns processing at once | 2 | global | queue, see below |

- **Window.** Sliding-window counters in memory (a deque of timestamps per key), injected clock for tests. Counters
  for idle sessions and IPs are dropped after their window passes, so memory is bounded by the active set. A
  hard bound on tracked keys (default 10000) evicts the oldest.
- **Retry-After.** Every `429` carries `Retry-After` (seconds) and a `message` the UI can show.
- **Client IP.** The socket address, unless `TRUST_PROXY=true`, in which case the last address of
  `X-Forwarded-For` appended by the trusted proxy is used (and if absent, the socket address). With the flag off the
  header is ignored, so it cannot be spoofed by direct clients.
- **Global concurrency (the Ollama bottleneck).** A semaphore of `MAX_PARALLEL_TURNS` (2) guards the work of a turn.
  A turn that cannot start waits in a queue of at most 4 for up to 20 s; beyond that it is refused with
  `429 busy` + `Retry-After`. The wait happens before the turn starts, so no half-played turn is abandoned. While
  queued the SSE stream sends a `queued` event (position) so the UI can say "waiting for a detective".
- **Idle expiry.** A background task runs every minute. A game with no turn for `GAME_IDLE_MINUTES` (30) is closed
  and its slot freed; the transcript is dropped. A later request for it returns `410 cold` ("that case went
  cold"), which the UI shows with a button to start a new game. After 24 h the id is forgotten and answers `404`.
  A save is the way to keep a game longer.

## 4. Jev budget and slow mode

- **BudgetGate.** A thin decider wrapper in `decider/` (next to `shadow`) with the same interface as the decider the
  agent already uses. For each decision it asks the gate whether Jev is available today.
  - Available: delegate to the normal decider (Jev primary, Nimble shadow).
  - Exhausted: delegate to a Nimble-only decider (no Jev call, no shadow), exactly the behaviour of `SHADOW_RUN=false`.
- **Accounting.** Daily Jev input tokens and call count, per UTC day, stored in the stats database (a small
  `jev_usage(day, tokens, calls)` table) so a restart does not reset the day. The gate reads the running total from
  memory and writes through. A call that fails still counts as one call (it may be billed). Tokens are taken from
  the response; when absent, an estimate of the request size is used.
- **Settings.** `JEV_DAILY_TOKENS` (5,000,000) and `JEV_DAILY_CALLS` (20,000); 0 = unlimited. The cap is checked
  before each call, so it can be overshot by at most the calls in flight (bounded by the concurrency cap).
- **Rollover.** At 00:00 UTC the next decision sees a new day and uses Jev again.
- **Health.** `/api/health` gains `mode: "normal" | "slow"`. The UI shows a small notice in slow mode and keeps
  playing. Games already open continue.
- **No new toggle.** `SHADOW_RUN` stays env-only; the gate can only force slow mode, never turn Jev on.
- **Missing Jev key.** Unchanged: the game is off with the reason in `/api/health`, unless `SHADOW_RUN=false`.

## 5. Admin

- **Gate.** A dependency `require_admin` on `/api/stats/decisions`, `/api/decisions`, `/api/decisions/{id}` and the
  new `/api/admin/usage`. `ADMIN_TOKEN` unset: all of them return 404 `not_found` (the routes behave as absent).
  Set: the `Authorization: Bearer <token>` header is compared with `hmac.compare_digest`; wrong or missing is
  `401 unauthorized`. Failed attempts count against the per-IP request limit twice, and are logged (IP only).
- **`/api/admin/usage`.** Today's Jev tokens and calls against the caps, mode, sessions seen, games open, saves held,
  queue depth. Read only.
- **Stats page.** `#/stats` asks for the token (a password field), keeps it in `sessionStorage`, sends it on every
  admin call, and shows "enter the admin token" on 401/404. The title screen's "Stats" button is removed from the player-facing flow; the owner opens `#/stats` by its address.
- **Players' text.** Because the endpoints are admin-only, `state_preview` stays in them (it is how disagreements
  are read). A startup purge deletes decision rows older than `DECISION_RETENTION_DAYS` (30; 0 = keep forever).
  The title screen gets a single line: "Your messages are kept to compare AI models." (owner to approve the wording).

## 6. Exposure

- **Serving the UI.** If `frontend/dist` exists the API serves it at `/` (assets with long caching, `index.html`
  with `no-cache`) and falls back to `index.html` for non-API paths that are not files. One origin serves both, so
  the UI and API need no CORS. `CORS_ORIGINS` stays for local dev (UI on 5173); with it empty no CORS headers are sent.
- **Headers on every response.** `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self'
  'unsafe-inline'` (inline styles only, because of the UI libraries; scripts stay `'self'`),
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`. API responses carry
  `Cache-Control: no-store`.
- **Docs.** `/docs`, `/redoc` and `/openapi.json` are off unless `API_DOCS=true`.
- **Binding.** Unchanged: `127.0.0.1`. Opening to the network is the tunnel's job; `__main__.py` warns if
  `API_HOST` is not loopback while `ADMIN_TOKEN` is unset.
- **Logging.** One line per refused request (code, route, session id prefix of 6 chars, IP). Typed text, cookies and
  tokens are never logged.

## 7. Components and file layout

| Piece | Where |
|---|---|
| Session cookie, signing, `Session` dependency | new `api/session.py` |
| Origin check, security headers, no-store | new `api/shield.py` (middleware) |
| Counters, `RateLimiter`, `TurnGate` (semaphore + bounded queue) | new `api/ratelimit.py` |
| Admin dependency | new `api/admin.py` |
| Ownership, idle expiry, `slot_for` | `api/service.py` |
| Save owner sidecar, per-session listing | `api/wiring.py`, `api/service.py` |
| `BudgetGate`, usage table | new `decider/budget.py`, `stats/store.py` |
| Static serving | `api/app.py` (or new `api/static.py`) |
| New settings | `config.py` (+ `.env.example`) |
| UI: busy/slow/cold notices, queued event, admin login | `frontend/src` |

Errors reuse `api/errors.py` and the `{code, message}` body; new codes: `rate_limited`, `quota`, `busy`, `cold`,
`forbidden`, `unauthorized`. The contract doc is updated in the same change.

## 8. Testing

Test-first, each piece with a fake clock where time matters.

- Cookie: valid, tampered, missing, wrong secret, `Secure` flag with the forwarded scheme.
- Ownership: another session's game, turn, confirm, transcript, save, delete and load all answer exactly like a
  missing game (same status, code and message); listing shows only own games and saves.
- Origin check: missing, foreign, matching, `GET` untouched, non-JSON body.
- Limits: each row of the table, window expiry, key-count bound, `Retry-After`, `TRUST_PROXY` on and off (spoofed
  header ignored when off).
- Concurrency: `MAX_PARALLEL_TURNS` respected, queue order, `busy` after the wait, queued event, a client that leaves
  the queue frees its place.
- Idle expiry: closes after the idle time, frees the slot, `410` then `404`, a save survives.
- Budget: below the cap Jev is used; at the cap Nimble alone and no Jev call; rollover; restart keeps the day's total;
  `0` = unlimited; failed calls count.
- Admin: token unset (404 everywhere), wrong, right; stats page flow in Vitest; Playwright smoke test through the
  cookie path.
- Security tests: no admin route reachable without the token; chat text cannot read hidden case data (existing tests
  stay green); a tampered save still refused.
- Live check once at the end: set `JEV_DAILY_TOKENS` tiny, play a few turns, confirm slow mode begins and `/api/health`
  reports it (a few cents at most).

## 9. Risks and open points

- **Single process.** Counters, sessions' ownership and games are in memory; a second process would break the
  limits. Acceptable for one machine; stated here so nobody scales it by accident.
- **Restart loses live games** (saves survive), and with a generated secret, sessions too. Setting `SESSION_SECRET`
  keeps cookies valid, but games are still gone.
- **Slow mode quality.** Nimble alone was too slow in the shadow run (12-26 s median on this machine, confounded).
  Slow mode may feel broken at those latencies; the clean latency run decides whether it is usable. The turn timeout
  and the busy path still protect the server.
- **Token estimate.** If the Jev response omits usage, the gate estimates; the cap is approximate by design.
- **Wording and numbers** in sections 3 and 4 are defaults to tune after real traffic; they are settings, not code.
- **Privacy notice** wording needs the owner's approval, and retention of 30 days is a default, not legal advice.
