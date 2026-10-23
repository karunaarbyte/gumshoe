# Gumshoe web UI (sub-project 5): design

Date: 2026-10-15. Status: draft for review. Builds on the API contract
(`docs/superpowers/specs/2026-10-13-api-contract.md`), which is the only interface between the UI and
the backend. No backend change is part of this spec.

## 1. Purpose and success

**Purpose.** A game to play and show off. The player investigates a generated case by chatting in free
text with an agent and the suspects, collects evidence on a corkboard, and finally accuses. The
Jev-versus-Nimble comparison is a side feature in a drawer; it does not drive the layout.

**Success looks like:**
- A new player can start a case, play it to a won or lost ending, and see the reveal, using only the UI.
- Reloading the page (or opening a saved game) restores the board, the chat, and any waiting
  confirmation exactly.
- A spend (accusation, give-up) can never happen by accident: every one passes through a visible
  confirmation, and the UI never sends a yes without the waiting `pending_id`.
- Anyone can open the trace drawer and see, per turn, what Jev and Nimble each decided, how confident,
  how fast and at what estimated cost, with disagreements highlighted.
- It looks like a noir case file ("Newsprint" style, section 4), not a generic chat app.

**v1 scope (agreed):** the play loop, persistence (saves, load, resume, reload), and the decision-trace
drawer. **Deferred:** the aggregate stats dashboard (`/api/stats/decisions`), mobile layout, autosave,
accounts.

## 2. Stack and setup

- React + TypeScript + Vite + Tailwind + Framer Motion. TanStack Query for plain REST reads. Vitest +
  React Testing Library for unit and component tests, Playwright for one smoke test.
- Lives in `frontend/` in this repo with its own `package.json`. The API does not serve the built UI
  (out of scope in the contract).
- Dev: `uv run gumshoe-api` (port 8000) and `npm run dev` (port 5173) with Vite proxying `/api` to
  8000. This avoids CORS and the plain-text preflight quirk listed in the contract.
- Fonts are self-hosted with fontsource (no third-party CDN at runtime): Courier Prime for body and
  Special Elite for headings and stamps (both open licences).
- Desktop-first, minimum width about 1100px. Animations respect `prefers-reduced-motion`. The chat is
  fully keyboard-usable; the board supports mouse and touch drag.

## 3. Screens and flow

**Title screen.** "New case" with an optional seed (random if empty) and a preset picker from
`GET /api/meta`. Below it: saves (`GET /api/saves`, Load) and open games (`GET /api/games`, Resume,
showing outcome and `turn_running`). If `GET /api/health` says the game is `off`, a banner shows the
reason and the New/Load/Resume controls are disabled.

**The Desk (main screen).** Three columns plus a bottom drawer:
- Left rail: the notebook (facts grouped by source with speaker, records, contradictions) and the
  Accuse button.
- Centre: the corkboard.
- Right rail: the chat.
- Bottom: the trace drawer, slides up on demand.

**Game over.** The ceremony (section 5.3), then the reveal card and "New case".

**Reload and resume.** Opening any game rebuilds everything from `GET /api/games/{game}` (brief,
notebook, outcome, pending, reveal) and `GET /api/games/{game}/turns` (transcript). A waiting
confirmation is restored from `pending` and can be answered with the same id. If the last transcript
turn has `complete: false`, the UI shows "turn running" and polls `/turns` until it completes.

## 4. Visual style: Newsprint

Warm paper background, black ink, hard offset shadows, red string and red stamps, typewriter type.
Tokens (starting values from the approved mockup; Tailwind theme colours):
- paper `#d9cdb2` (background), card `#f3ecd8`, card-light `#fff9e8`, ink `#1a1713`, stamp red `#c4161c`.
- Cards are slightly rotated (about -2 to 2 degrees, deterministic per card), with a 1px ink border
  and a hard 3px 4px 0 ink shadow.
- Labels are small caps in an inverted ink chip ("SUSPECT"), names in bold typewriter capitals.
- Buttons: red stamp block with letter-spaced caps (ACCUSE); secondary buttons are outlined ink.

## 5. Components

### 5.1 Corkboard

Cards (all from `GameState`/brief; nothing invented):
- Suspects and locations: from `brief`. A `locked` card is shown face-down/redacted and flips when it
  unlocks.
- Facts: from `notebook.sections[].facts[]`, grouped by `source`, showing `speaker` when present.
  `contradicted` facts carry a red CONTRADICTED stamp.
- Record kinds: labelled index cards from `brief.record_kinds`.

Strings:
- **Game strings (red):** drawn automatically for each `notebook.contradictions` entry (lie fact to
  exposer fact) and for each fact's `relates_to` entries (suspect display names, matched to the open
  suspects' cards by name). Suspect and place cards are keyed by their brief `number` (fixed for the
  case, across unlocks and a load), never by name: a locked one arrives with an empty name.
- **Player threads (black ink, dashed):** the player drags from a pin on one card to another to make a
  thread, and clicks a thread to delete it. Threads are personal theories: unlabelled, no effect on
  the game.

Layout and persistence:
- Initial placement is deterministic per card type (suspects across the top, places and evidence below,
  jitter seeded from the card handle). Dragging a card overrides its position.
- Positions and threads are stored in `localStorage` keyed by game id. Game ids are temporary (a
  server restart or a load yields a new one), so pressing Save in the UI also copies the layout and
  threads under the save name, and loading that save restores them. A game that was never saved and is
  lost to a server restart loses its arrangement; this is accepted for v1.

### 5.2 Chat

One stream rendering events with the same visual language:
- Player messages: typed slips, right-aligned.
- `reply`: shows `speaker`; replies with `source` `canned` or `degraded: true` carry a small tag.
  `source: help` renders as an agent note.
- `tool_call` / `tool_result`: compact collapsible "case file" lines; `ok: false` is a red error line.
- `intent` and `post_check`: hidden in the chat, shown only in the trace drawer.
- `clarify`: an agent line. For `reason: accusation`, each `problems[]` entry becomes a row of picker
  buttons from `options`; clicking one sends a normal turn whose text is exactly the option's `name`
  (the agent parses it against the accusation in progress; the UI does not build accusation sentences).
  Whether the agent accepts a bare name for `how` and `why` options is verified during the first
  real-backend manual run (section 9) and, if it does not, the picker text becomes a short sentence
  such as "I think it was <name>"; this is a one-line change in the chat component.
  `reason: pending` renders as an agent prompt next to the still-visible confirm card.
- `confirm`: an inline card with the `text`, any `warnings`, and Yes and No buttons calling
  `POST /confirm` with the `pending_id`. A typed yes while a confirmation waits sends a normal turn
  with the waiting `pending_id` in the body, so typing "yes" works. Without a waiting confirmation the
  UI never sends a `pending_id`.
- `cancelled`: a struck-through confirm card.
- Input: disabled with a typing indicator while a turn runs (the server answers 409 otherwise). Text
  limited to `meta.max_turn_chars`.

### 5.3 Accusation ceremony

On `game_over` (or when a reloaded game's `outcome` is not `playing`): a full-screen sequence. A red
thread pulls tight to the culprit's card, a stamp slams down (CASE CLOSED for a win, FILE REMAINS OPEN
for lost or gave_up), then the reveal card shows culprit, method, motive and secret. With
reduced-motion the sequence is replaced by a static reveal card.

### 5.4 Trace drawer

- Lists the current game's turns, newest first. Each turn expands to its decisions, found from the
  `decision_id` fields of `intent`, `clarify`, `post_check` and `confirm` events.
- Each decision is fetched from `GET /api/decisions/{id}`; a 404 `not_recorded_yet` is retried a few
  times with a short backoff (the primary's row can land a moment after the event).
- A decision shows Jev and Nimble side by side: per question the verdict and confidence, plus latency,
  tokens, estimated cost, a `used` badge, `fallback`, `cold`, and the error line (class, backend,
  status only). Rows whose verdicts differ are highlighted. `state_preview` is available in an
  expander.
- Header: running totals for the open game (calls, summed estimated cost, mean latency per backend)
  computed from the decisions already loaded. Backend names come from `GET /api/health`; with no
  shadow the drawer is one column.

## 6. State and data flow

- **Event-folding store.** One reducer folds every stream event into a single game view model:
  messages, pending confirmation, outcome and reveal, turn status, and per-turn decision ids. The
  initial model is built from `GET /games/{game}` and `/turns` using the same fold, because `/turns`
  events have the same shape as the live stream. The live path and the reload path therefore cannot
  drift apart.
- **Stream reader.** `fetch` with a stream reader (the turn endpoints are POST, so `EventSource`
  cannot be used). It parses `event:`/`data:` blocks, ignores `: ping` comment lines, tolerates chunk
  boundaries anywhere, and yields typed events.
- **REST.** TanStack Query for meta, health, saves, games, and decision lookups. Mutations: create,
  load, save, delete.
- **Types.** Hand-written TypeScript types mirroring the contract. Contract drift is caught by tests
  that replay fixture streams, not by runtime schema checks (YAGNI).

## 7. Errors

One typed client turns every non-2xx body into `ApiError(code, message)`. Handling:
- `unavailable`: full-screen "the game is off" panel with the health reason.
- `unknown_game`: "this game has ended (the server may have restarted)", back to the title screen.
- `turn_in_progress`: soft notice, input stays disabled until `done`.
- `too_many_games`, `bad_save`, `bad_argument`, `bad_request`, others: a short toast with the server's
  message (which never echoes the player's text).
- A stream that ends without `done`, or a network failure mid-turn: "connection lost", then reload
  state and transcript (the same path as a page reload). The server keeps running a turn whose client
  left, so the reload shows its outcome.

## 8. Code layout (`frontend/src/`)

- `api/`: typed client, stream reader, contract types.
- `game/`: reducer, store, turn hook (sends turn/confirm, feeds the stream into the reducer), reload.
- `board/`: card components, string rendering, deterministic layout, player threads, storage.
- `chat/`, `notebook/`, `trace/`, `ceremony/`: one folder each.
- `screens/`: title and desk.
- `theme/`: Tailwind tokens, fonts.

Each unit has one purpose and a narrow interface: `api/` knows HTTP and nothing about React,
`game/` knows events and nothing about layout, `board/` knows layout and nothing about HTTP.

## 9. Testing

- **Vitest unit tests:** the reducer for every event type; a check that folding a fixture's `/turns`
  events yields the same model as folding the same events as a live stream; the stream reader
  (chunk boundaries, pings, malformed block); layout determinism; storage keys and the
  save-name copy.
- **Component tests (React Testing Library):** the confirm flow (Yes button, typed yes sends the
  `pending_id`, No/cancel, a bare yes without a waiting confirmation sends no `pending_id`); accusation
  pickers; input disabled while a turn runs; the drawer's disagreement highlight and retry on
  `not_recorded_yet`; each error case in section 7.
- **One Playwright smoke test** against a small scripted fake API (canned SSE): new game, a turn, an
  accusation, confirm, game over and reveal.
- **Against the real backend:** a manual checklist in the frontend README, not an automated test,
  because that path is billed.

## 10. Out of scope and assumptions

- Out of scope: aggregate stats page, mobile layout, autosave, accounts or auth, serving the build from
  the API, internationalisation.
- The API stays loopback-only with no authentication (per the contract); the UI is not hardened for
  public exposure.
- Assumption: the contract is accurate. Known contract quirks the UI must tolerate: a full saves
  folder surfaces as a 500 `bad_save`; a loaded game that was given up reads `lost`; a turn cancelled by
  server shutdown can give an empty stream (handled by the reload path in section 7).
- Risk: hand-written types can drift from the backend. Mitigation: fixture streams in tests, and the
  contract document is the single reference.
