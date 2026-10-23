# Public hardening (stage 4) design

Date: 2026-10-16 (revised after an independent review the same day). Status: draft for the owner's review.
Follows `docs/superpowers/roadmap-after-5.md` (stage 4) and the API contract `2026-10-13-api-contract.md`.

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
| Budget cutoff | When a Jev cap is reached the game falls back to Nimble alone ("slow mode"), it does not close |
| Admin | `ADMIN_TOKEN` in `.env`, sent as `Authorization: Bearer`. Unset means the admin endpoints do not exist (404) |
| Out of scope | Accounts, leaderboards, cross-device saves, games surviving a restart, CAPTCHA, WAF, multi-instance deployment |

Decisions made while revising after review (owner may override): the player trace drawer stays, served by an
owner-scoped redacted endpoint (section 5); a Jev share per client IP, not only a global cap (section 4); saves
expire and can be deleted (section 2).

Success: a stranger can play a full game; cannot read or affect another player's game, save or text; **one client
cannot, by itself, use up the global game, save, turn or Jev capacity** (each capacity has a per-client share, and
the global ceilings stay as the last line); and the owner can still use the stats page and read disagreements.

## 2. Public mode, sessions and ownership

- **Public mode.** `PUBLIC_ORIGIN` (e.g. `https://gumshoe.example.com`) turns on the public-site behaviour that
  needs to know the real address: the Origin check, the `Secure` cookie, the `__Host-` cookie name and the startup
  checks below. Unset means local development: the Origin check accepts the request's own `Host` and any
  `CORS_ORIGINS` entry, cookies are not `Secure`.
- **Startup checks.** The server refuses to start in public mode without `SESSION_SECRET` (at least 32 characters)
  and without `ADMIN_TOKEN` (at least 32 characters) unless `ADMIN_TOKEN` is deliberately empty (admin off). It logs
  a warning when `PUBLIC_ORIGIN` is https or the bind address is not loopback but `TRUST_PROXY` is false, and when
  `TRUST_PROXY` is true but `API_HOST` is not loopback.
- **Cookie.** Name `__Host-gs_session` in public mode (`gs_session` otherwise). Value `<id>.<sig>`: `id` is 128
  random bits (url-safe), `sig` is HMAC-SHA256 of `id` with the cookie key. Attributes: `HttpOnly`,
  `SameSite=Lax`, `Path=/`, `Max-Age` 30 days, plus `Secure` in public mode. A bad or missing signature is treated as
  no cookie (never an error). The signature is compared with `hmac.compare_digest` on **bytes** (a non-ASCII value
  must not raise).
- **Keys.** The cookie key and the save-owner key are derived from `SESSION_SECRET` with distinct labels (HKDF or an
  HMAC of the label), so one cannot be replayed as the other. In local mode with no `SESSION_SECRET`, a random secret
  is generated at start and a warning says that sessions and save ownership reset on restart. Rotating the secret
  orphans existing saves (stated, not hidden).
- **Issue.** A session is issued only on `POST /api/games` and `POST /api/games/load`. Health, meta, static files,
  admin and every other route never issue one, so monitors and crawlers do not use up "new sessions". A game route
  called with no valid session answers `unknown_game` (404).
- **Ownership.** `_Slot` in `api/service.py` gains `owner: str`. Every `/api/games/{game}/...` route takes the
  session as a dependency and calls one `service.slot_for(game, session)`. A game that does not exist, one owned by
  someone else, and one that expired (for a non-owner) are **indistinguishable**: the same `unknown_game` 404 with
  the same message, checked before any lock, turn or save is touched.
- **Listing.** `GET /api/games` filters the slots by owner **before** any engine call (today it asks the engine for a
  brief per slot, so filtering afterwards would cost one call per game in the process for every list request).
- **Saves.** Save files are named by the host and persist. Right after a successful `save_game` the service writes
  an owner sidecar `<name>.owner` (atomic write, content: a keyed hash of the session id). Until it exists the
  save is invisible. `GET /api/saves` checks the sidecar before reading the case. `POST /api/games/load` of a save the
  caller does not own answers exactly as for a missing one (`bad_save`, "that save cannot be read"). A loaded save
  counts as an open game against the session quota. Saves without a sidecar (made before this change) belong to
  nobody; the owner can delete or adopt them from the shell.
- **Save lifecycle.** `DELETE /api/saves/{name}` (owner only). A purge at startup and then hourly deletes saves older
  than `SAVE_RETENTION_DAYS` (30; 0 = keep). Without these, the global save cap could be filled permanently.
- **CSRF.** Every `POST`/`DELETE` must carry an `Origin` (or failing that a `Referer`) that is one of: the
  `PUBLIC_ORIGIN`, or in local mode the request's own origin, or a `CORS_ORIGINS` entry. Otherwise `403 forbidden`.
  `GET` never changes state. Requests with a body must be `application/json`. The UI uses `fetch` for everything
  (also the SSE turn stream, which is a `POST`), so browsers always send `Origin`; scripts (curl) must set it.

## 3. Limits and the turn gate

All numbers are settings (0 = unlimited, for local testing).

| Limit | Default | Scope | Answer |
|---|---|---|---|
| Games open at once (created or loaded) | 3 | session | `429 quota` |
| Games created per hour | 20 | session | `429 rate_limited` |
| Saves held | 10 | session | `429 quota` |
| Turns per minute | 30 | session | `429 rate_limited` |
| Turn in flight | 1 | game (exists), and 1 per session | `409` as today |
| New sessions per hour | 10 | client IP | `429 rate_limited` |
| Requests per minute | 300 | client IP | `429 rate_limited` |
| Turns per minute | 60 | client IP | `429 rate_limited` |
| Turns in flight | 2 | client IP | `429 busy` |
| Games open / saves held | 6 / 20 | client IP | `429 quota` |
| Games open / saves held | 200 / 500 | global (was 1000 / 500) | `too_many_games` / `bad_save` as today |
| Turns processing at once | 2 | global | queue, below |

- **Counters.** Sliding-window counters in memory (a deque of timestamps per key) with an injected clock. A key
  whose window has passed is dropped. The table is bounded (default 20000 keys): **only expired keys are evicted;
  when the table is full of live keys new keys are refused with `429 rate_limited`** (fail closed), so an attacker
  rotating sessions or IPs cannot flush a victim's counters.
- **Retry-After.** Every `429` carries `Retry-After` in seconds (`busy`: 5) and a `message` the UI can show.
- **Client IP.** The server starts uvicorn with `proxy_headers=False`, so the socket address is the only thing
  uvicorn reports; the forwarded header is handled in `ratelimit.py` alone. With `TRUST_PROXY=false` the header is
  ignored. With `TRUST_PROXY=true` the client is the **last** `X-Forwarded-For` entry, which is correct for exactly
  one trusted proxy hop (the tunnel); a deployment with more hops needs a different rule and is out of scope. If
  the header is absent the socket address is used. IPv6 clients are grouped by /64.
- **Where the gate sits.** `MAX_PARALLEL_TURNS` (2) guards the work of a turn. In `AgentService._run` the turn first
  takes its game lock, then the gate, so a long save never holds a gate slot. Behaviour:
  - Queue full (4 waiting): `start_turn`/`start_confirm` refuse **synchronously** with `429 busy` before any stream
    starts, so it is a real HTTP 429.
  - Waiting: the stream sends a `queued` event (position). This event is added to the `TurnEvent` union, the
    frontend event types and reducer, and is **not** stored in the transcript or replayed by `rebuild`.
  - Waited over 20 s: the stream ends with a `clarify` event (`reason: "error"`, text "the detectives are busy, try
    again in a moment") and `done`; nothing is recorded in the transcript, as for any turn that did not run.
  - The reader leaves while queued: the gate wait is cancelled, so an abandoned request does not hold a queue place.
- **Shadow gate.** The Nimble shadow call outlives the turn (`ShadowDecider` returns Jev's answer and finishes the
  shadow in the background), so the turn gate alone does not bound Ollama. Shadow calls get their own semaphore
  (`SHADOW_PARALLEL`, 1) and are skipped, not queued, when it is busy: a skipped shadow writes no shadow row, so the
  decision is simply uncompared (the stats already treat that case). The number skipped is shown in the admin usage.
- **Idle expiry.** A task runs every minute. A game idle for `GAME_IDLE_MINUTES` (30), measured from the end of its
  last turn, is closed unless its slot is busy; it takes the slot lock first. Its slot is freed and the transcript
  dropped. A tombstone `(owner, game)` is kept for up to 24 h in a map capped at 5000 entries (oldest evicted).
  The owner then gets `410 cold` ("that case went cold"); anyone else, and the owner after the tombstone is gone,
  gets the ordinary 404. A save is the way to keep a game longer.
- **Memory.** Per-game transcripts stay capped at 200 turns; with 3 games per session and 200 games globally the
  worst case is bounded and listed in the admin usage. (`MAX_GAMES` becomes a setting; 1000 stays the default in
  local mode, public mode defaults to 200.)

## 4. Jev budget and slow mode

- **UsageLedger.** `decider/` may not import `gumshoe.stats` (enforced by `tests/test_architecture.py`), so the gate
  depends on a small `UsageLedger` protocol defined in the decider package (add Jev tokens for a day and a client
  key; read totals). `SqliteStatsStore` implements it (a `jev_usage(day, key, tokens)` table) and is passed to the
  decider factory. The architecture test's layer rules are updated for the new module.
- **BudgetGate.** A decider wrapper with the same interface the agent already uses, built beside `ShadowDecider`. It
  owns two deciders: the normal one (Jev primary, Nimble shadow) and a Nimble-only one
  (`make_decider(backend="nimble")`, no shadow). It closes both on exit. For each decision it chooses:
  Jev available → normal; otherwise → Nimble only, exactly the behaviour of `SHADOW_RUN=false`.
- **Accounting.** Jev input tokens per UTC day, globally and per client IP, from the usage already parsed from each
  response (the Jev rows in the shadow data all carry tokens). A call that fails counts an estimate of its request
  size (it may be billed). There is no separate calls cap.
- **Caps.** `JEV_DAILY_TOKENS` (5,000,000, about 4,000 calls or 150 games at the measured 1.2k tokens per call and
  27 calls per game) and `JEV_IP_DAILY_TOKENS` (300,000, about 8 games per client IP per day); 0 = unlimited. The cap
  is checked before each call, so it can be overshot by the calls in flight.
- **Per-IP share.** A client IP over its share gets slow mode for itself while others still use Jev, so one visitor
  cannot drain the global cap. The key is the client IP (section 3), because a session can be recreated.
- **Recording.** Nimble-only decisions are recorded as primary rows for `nimble`, as `SHADOW_RUN=false` does today.
  The stats already handle windows that mix both and show exactly one primary per node.
- **Rollover.** At 00:00 UTC the next decision sees a new day.
- **Health.** `/api/health` gains `mode: "normal" | "slow"` (global cap only; a per-IP slow mode is not reported
  there). The UI shows a small notice in slow mode and keeps playing. Games already open continue.
- **No new toggle.** `SHADOW_RUN` stays env-only; the gate can only force slow mode, never turn Jev on.
- **Missing Jev key.** Unchanged: the game is off with the reason in `/api/health`, unless `SHADOW_RUN=false`.
- **Latency target for slow mode.** Nimble measured 12-26 s per decision on this machine (confounded; a clean run is
  pending) and about 3 decisions per turn, which approaches the 20 s queue wait and the 120 s turn timeout. Slow mode
  is only acceptable if a clean run shows a turn in roughly 20 s or less; otherwise slow mode will mostly show `busy`
  and the owner should prefer closing the game for the day. This is called out as a risk, not solved here.

## 5. Admin and the player trace drawer

- **Gate.** A dependency `require_admin` on `/api/stats/decisions`, `/api/decisions`, `/api/decisions/{id}` and the
  new `/api/admin/usage`. When `ADMIN_TOKEN` is unset, **and** when it is set but the header is missing or wrong, the
  answer is the same 404 `not_found`, so the routes cannot be told from absent ones. The token is compared with
  `hmac.compare_digest` on bytes and must be at least 32 characters (startup check). Failed attempts are limited to
  10 per minute per IP and logged (IP only).
- **`/api/admin/usage`.** Today's Jev tokens against the caps (global and top client IPs), mode, sessions seen, games
  open, saves held, queue depth, skipped shadows. Read only.
- **Stats page.** `#/stats` asks for the admin token (a password field), keeps it in `sessionStorage` (that tab
  only), and the shared `send()` in `frontend/src/api/client.ts` adds `Authorization: Bearer` to the admin calls
  only. A 404 clears the token and asks again with "That token did not work, or the stats are switched off.";
  "Forget the token" clears it and the cached stats. The title screen's "Stats" button is removed from the
  player-facing flow; the owner opens `#/stats` by its address.
- **Player trace drawer.** `Desk.tsx` renders `TraceDrawer` for every player, and it calls
  `GET /api/decisions/{id}`, which becomes admin-only. A new owner-only endpoint `GET /api/games/{game}/decisions/{id}`
  serves the drawer instead: it answers only the game's owner, and only for a decision id that appears in that
  game's own transcript events (the last 200 turns the server keeps). A stranger gets the missing game's answer; an
  id that is malformed or not in that transcript gets one plain 404. The decision is redacted by an allow-list
  (`api/redact.py`): **`state_preview` is removed**; numbers, flags and server-made strings (confidence, timing,
  token counts) stay; model answers are kept only for the `understand` and `post_check` nodes, and only those whose
  question names and verdicts are shape-checked tokens (such as `suspect_3`, `yes`, `2.00`), never free text; every
  other node shows no answers; a call's error shows only as `"failed"`, never its text. Admin keeps the full view.
- **Players' text.** Because the list endpoints are admin-only, `state_preview` stays in them (it is how
  disagreements are read). A purge in the startup housekeeping, then hourly, deletes decision rows older than
  `DECISION_RETENTION_DAYS` (30; 0 = keep forever). The title screen gets a single line: "Your messages are kept
  to compare AI models." (wording for the owner to approve).

## 6. Exposure

- **Serving the UI.** If `frontend/dist` exists (it is git-ignored, so serving is conditional) the API serves it at
  `/`: assets with long caching, `index.html` with `no-cache`, and `index.html` as the fallback for non-API paths that
  are not files. `/api/*` always keeps the JSON error shape and never returns `index.html`. File paths are resolved
  with a containment check (no traversal). One origin serves UI and API, so no CORS is needed; `CORS_ORIGINS`
  stays for local development.
- **Headers on every response.** `Content-Security-Policy: default-src 'self'; img-src 'self' data:;
  style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'`
  (the inline styles come from React `style` attributes; scripts stay `'self'`, which the built `index.html`
  satisfies), `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`.
  `Cache-Control: no-store` is added to **every** response (not only `/api/`) **where none is set**, so a disabled
  `/docs` looks like any unknown route, while the SSE route keeps its `no-cache` and `X-Accel-Buffering` headers and
  the UI files keep their own caching.
- **Docs.** `/docs`, `/redoc` and `/openapi.json` are off by default, also locally: local docs are opt-in with
  `API_DOCS=true`. Public mode (`PUBLIC_ORIGIN` set) refuses `API_DOCS=true` at startup. With the CSP above their
  pages will not load, which is noted in the setting's description.
- **Binding.** Unchanged: `127.0.0.1`. Opening to the network is the tunnel's job.
- **Logging.** One line per refused request (code, route, session id prefix of 6 chars, IP). Typed text, cookies and
  tokens are never logged.

## 7. Components and file layout

| Piece | Where |
|---|---|
| Cookie, keys, `Session` dependency, public-mode checks | new `api/session.py` |
| Origin check (pure ASGI middleware, like `BodyLimit`; a `BaseHTTPMiddleware` would break the SSE disconnect detection) | new `api/shield.py` |
| Security headers and no-store (pure ASGI middleware too) | new `api/headers.py` |
| Counters, `RateLimiter`, `TurnGate` (semaphore + bounded queue), client IP | new `api/ratelimit.py` |
| Admin dependency | new `api/admin.py` |
| Ownership, `slot_for`, owner filter, idle expiry, tombstones, queue behaviour | `api/service.py` |
| Save owner sidecar, per-session listing, save delete and purge | `api/wiring.py`, `api/service.py`, `api/games.py` |
| Owner-scoped trace endpoint | `api/games.py` |
| `UsageLedger` protocol, `BudgetGate`, shadow semaphore | `decider/` (+ `tests/test_architecture.py` rules) |
| `jev_usage` table, `UsageLedger` implementation, decision purge | `stats/store.py` |
| Static serving | `api/app.py` (or new `api/static.py`) |
| uvicorn `proxy_headers=False` | `api/__main__.py` |
| New settings, startup checks | `config.py` (+ `.env.example`) |
| UI: `queued`/busy/slow/cold notices, event type, admin login and auth header, drawer endpoint | `frontend/src` |

Errors reuse `api/errors.py` and the `{code, message}` body; new codes: `rate_limited`, `quota`, `busy`, `cold`,
`forbidden`. The contract doc is updated in the same change.

## 8. Testing

Test-first, each piece with a fake clock where time matters.

- **Existing tests that must change.** The 44 `post`/`delete` call sites in `tests/api/*` send no `Origin`, so they
  need a shared test client that sends one and keeps a cookie jar (`tests/api/conftest.py`, `helpers.py`). Tests of
  the decision and stats endpoints need the admin token. Frontend: `fakeApi.ts`, `e2e/fake-api.mjs`,
  `TitleScreen.test.tsx` (the Stats button) and `App.tsx` routing. `tests/test_architecture.py` for the decider layer.
- Cookie: valid, tampered, missing, non-ASCII value, wrong secret, `Secure` and `__Host-` in public mode, lazy issue
  (health and meta set no cookie).
- Ownership: another session's game, turn, confirm, transcript, save, delete, load and trace all answer exactly like
  a missing one (same status, code and message); the list shows only own games and saves and makes no engine call for
  others'; a save with no sidecar is invisible; the sidecar is written atomically after the save.
- Origin check: missing, foreign, matching, `PUBLIC_ORIGIN`, `CORS_ORIGINS`, `GET` untouched, non-JSON body.
- Limits: each row of the table, window expiry, fail-closed when full, no eviction of live keys, `Retry-After`,
  `TRUST_PROXY` on and off (spoofed header ignored when off), IPv6 /64 grouping, uvicorn rewriting disabled.
- Turn gate: queue order, synchronous `429 busy` when full, `queued` event, over-20 s ends with clarify and done and
  records nothing, a reader that leaves frees its place, the lock is taken before the gate, one session cannot hold
  both global slots, the shadow semaphore skips instead of queueing and leaves the decision uncompared.
- Idle expiry: closes after the idle time from the last turn's end, skips a busy slot, frees the slot, `410` for the
  owner and `404` for others, tombstone cap, a save survives. Save purge and delete.
- Budget: below the cap Jev is used; at the global cap and at a client's share Nimble alone and no Jev call;
  rollover; restart keeps the day's total; `0` = unlimited; failed calls count; both deciders closed on exit; the
  architecture test still passes.
- Admin: unset, missing and wrong token all 404 identically; right token works; short token refuses to start; the
  stats page flow in Vitest (token prompt, header sent only to admin calls); the player drawer works through the
  owner-scoped endpoint and shows no `state_preview`.
- Security: no admin route reachable without the token; chat text cannot read hidden case data (existing tests stay
  green); a tampered save is still refused (existing test); a path-traversal request never leaves `frontend/dist`;
  `/api/*` never returns `index.html`.
- Live check once at the end: set `JEV_DAILY_TOKENS` tiny, play a few turns, confirm slow mode begins and
  `/api/health` reports it (a few cents at most).

## 9. Risks and open points

- **Single process.** Counters, ownership and games are in memory; a second process would break the limits.
  Acceptable for one machine; stated so nobody scales it by accident.
- **Restart loses live games** (saves survive). A rotated `SESSION_SECRET` also orphans saves.
- **Slow mode quality** (section 4 latency target). The clean latency run decides whether it is usable.
- **Tunnel assumptions.** One trusted proxy hop and a forwarded-IP header; if the tunnel product differs, the client
  IP rule must be revisited before launch.
- **NAT.** A school or office behind one IP shares the per-IP limits (10 sessions per hour, 6 open games).
- **Defaults are guesses.** Every number is a setting to tune after real traffic.
- **Privacy notice** wording and 30-day retention need the owner's approval; retention is a default, not legal advice.
