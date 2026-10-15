# Sub-project 3: MCP server (design)

Date: 2026-10-12. Status: written spec, revised after self-review and two independent reviews;
plan written (`docs/superpowers/plans/2026-10-12-mcp-server-3.md`). **The plan's "Amendments" win over
this text**: the installed SDK is mcp 2.x (`MCPServer`, not `FastMCP`), its error wire format is the
SDK's, and `give_up`/`reveal` moved to task 2.
Parent: `2026-10-01-gumshoe-design.md` (sections 4 and 6, sub-project 3) and
`2026-10-01-case-engine-design.md` (5.2 spoiler boundary, 5.3 tool semantics, 5.4 accusation flow,
5.5 saves, 5.6 personas). Where this spec is more specific it wins; section 12 lists the one
deliberate departure from the parent (`reticent` dropped).

## 1. Outcome and trust model

`python -m gumshoe.mcp_server` starts a stdio MCP server through which an agent (or the standard MCP
inspector) can start a game on a generated case and play it to the end: look at places, question
suspects, read records, read the notebook, accuse, give up, reveal, fetch a suspect's persona brief,
check a suspect's reply, save and load. The same behaviour is available in-process by calling
`GameHost` directly, so the agent loop (sub-project 4) and the tests do not need the protocol.

The server holds the spoiler-bearing case server-side and returns only player-safe views. It makes
no model calls and knows nothing about the Decider.

**Trust model.** The MCP client is the trusted agent loop, running on the operator's machine, not a
player-controlled client. `persona_brief` and `check_reply` are agent-only material: a client that
could call them directly could probe them (for example `check_reply` reports per-axis violation
counts, which a crafted reply can use to test whether a word belongs to a candidate the player has
not unlocked). Nothing in this sub-project exposes the server to a player directly; sub-project 4/5
must keep it that way. The player-facing tools return exactly what the engine already allows a
player to see.

**Seeds and forks.** A seed is the whole case. Any client can start `new_game` on a running
game's seed (or `save_game` then `load_game`) and `give_up` on the copy to read the truth of the
game still being played. This cannot be closed in the engine and is acceptable only because the
client is the trusted agent loop; if agents ever play for untrusted users, the API layer must
restrict seeds and `give_up` per session. `tools.INSTRUCTIONS` says so too.

## 2. Decisions (made in brainstorming)

1. **Games are started and held by tools.** `new_game(seed, preset, pack)` returns a game id; every
   other tool takes the game id. One server holds many games in memory. Rejected: one game per
   process (awkward for the UI), and stateless tools that carry `PlayState` (the case still has to
   live server-side).
2. **Jev parsing stays out of the server.** The agent loop turns the player's words into candidate
   handles with Jev. The server's `accuse` takes resolved handles.
3. **`persona_brief` is built here** (pure engine function in `play/`, tested) and exposed as a tool,
   next to `check_reply`.
4. **Architecture B:** a framework-free `GameHost` does all the work; the FastMCP tools are one-line
   adapters. Rejected: logic inside the tool functions (untestable without the protocol), and MCP and
   FastAPI in one app.

## 3. Package and boundaries

New package `src/gumshoe/mcp_server/` (outside `cases/`; the `mcp` SDK is a new dependency).

```
mcp_server/
  errors.py     GameError(code, message) and the code set
  host.py       GameHost: game table, saves; every public method returns a view
  tools.py      FastMCP adapters: one function per tool, each calls GameHost and maps GameError
  __main__.py   python -m gumshoe.mcp_server  (stdio)
```

- **One import face.** The existing test `test_code_outside_cases_uses_only_the_cases_public_api`
  (`tests/test_architecture.py`) bans any `gumshoe.cases.*` import from code outside `cases/`, and
  stays unchanged. So `mcp_server` imports only `gumshoe.cases` (the top level), plus the stdlib,
  pydantic and, in `tools.py` / `__main__.py` only, the `mcp` SDK. `host.py` does not import `mcp`.
- **New exports** on `gumshoe.cases` (added in task 1, with the architecture docstring updated):
  the views the tools return (`PlayerCaseView`, `SourceResult`, `NotebookView`, `AxisOptions`,
  `AccusationPlan`, `AccusationResult`, `ParsedAccusation`, `RevealView`, `ReplyCheck`,
  `PersonaBrief`), the base class `View` (so `NewGame` and `SaveRef` are `View`s, frozen, no extra
  fields), the engine errors `GameOver`, `GameNotOver`, `StateMismatch`, `UnsupportedPreset`, and
  two new ones added in task 1: `HandleCollision(ValueError)`, raised by `_make_handles` instead of
  a bare `ValueError`, and `UnknownHandle(LookupError)`, raised by `GameSession.persona_brief` for a
  handle that is not a suspect. Also exported: `supported_presets` and the builtin pack loader
  `load_builtin_pack` with `BuiltinPackError`, re-exported from `tools/builtin.py` in
  `cases/__init__.py` (package-level files are exempt from the layer rule, and `__init__` already
  imports `generate`, so there is no cycle).
- **New architecture rule:** `mcp_server` is an allow-list of exactly `gumshoe.cases`, `mcp`, the
  stdlib and pydantic; it may not import `gumshoe.decider`. `gumshoe.cases` imports nothing from
  `mcp_server`.
- "No skeleton type in any result" is not an import rule (an ast rule cannot see return values); it
  is a test over real tool results (section 8.3).
- The host never holds a `Case`: it generates one, stores `dump_case(case)` bytes for saves, and
  builds the session with `load_session(bytes, salt)`. `load_session` does **not** verify the case
  itself (it only checks that a given state belongs to the case). So `load_game` also checks
  `skin_hash(case) == case.skin_hash` and runs `validate_case` (both exported), and a failure of
  either is `bad_save`.

## 4. `GameHost`

```
GameHost(ids: IdSource | None = None, saves_dir: Path | None = None)

IdSource: a Protocol with one method, next() -> str, returning exactly 16 lowercase hex
characters. The default draws them at random. Game ids, salts and save names all come from it.

new_game(seed: int, preset: str = "standard", pack: str = "castle") -> NewGame
case_brief(game) -> PlayerCaseView
search(game, location) -> SourceResult
interrogate(game, suspect) -> SourceResult
check_records(game, subject, kind=None) -> SourceResult
notebook(game) -> NotebookView
nameable(game, axis) -> AxisOptions
describe_accusation(game, who=None, how=None, why=None) -> AccusationPlan
accuse(game, who, how, why, confirmed=False) -> AccusationResult
give_up(game) -> RevealView          # session.give_up() (returns None), then reveal()
reveal(game) -> RevealView
persona_brief(game, suspect) -> PersonaBrief
check_reply(game, suspect, player_text, reply) -> ReplyCheck
save_game(game) -> SaveRef
load_game(name) -> NewGame
```

- **Ids and salts.** A game id is an opaque string from the injectable `IdSource` (default: random
  hex, not derived from the seed). Each game also draws a salt from it for the handles. If the
  session raises `HandleCollision`, the host draws the next salt and retries (and catches it before
  any other `ValueError`, because `StateMismatch` and pydantic's `ValidationError` are also
  `ValueError`s). Save names come from the same source. With a pinned source, identical call sequences give byte-identical outputs;
  tests pin it.
- **`new_game`.** `pack` is looked up with `load_builtin_pack` (cached per name); a
  `BuiltinPackError` is `bad_argument`. `seed` must be a real int (`type(seed) is int`, so `True` is
  refused) in `0 .. 2**63 - 1`; the generator itself accepts negative and huge seeds, so the host
  bound is the only guard. `UnsupportedPreset` is the real preset check (generation needs the
  preset in `pack.presets` and the capacity checks, which `supported_presets` does not cover; the
  host advertises no preset list of its own). `UnsupportedPreset` and `CaseGenerationError` are
  `bad_argument` with a short message (no generator internals).
  `NewGame(game, brief)` carries the id and the opening brief.
- **End of game.** `give_up` sets the status to `lost` (there is no separate "given up" state).
  Per-tool behaviour once the game is over:

  | Tool | After won/lost |
  |---|---|
  | `search`, `interrogate`, `check_records`, `accuse`, `give_up` | `GameError("game_over")` |
  | `case_brief`, `notebook`, `nameable`, `persona_brief`, `check_reply`, `save_game` | allowed, unchanged |
  | `describe_accusation` | allowed; `can_confirm` is false |
  | `reveal` | allowed only after the end; while playing `GameError("not_over")` |

- **Argument limits.** `player_text` and `reply` are at most 4000 characters each, otherwise
  `bad_argument`. A bad `axis` for `nameable` (not `who | how | why`) is `bad_argument`; the host
  validates it before the engine's `Axis(axis)` can raise.
- **Concurrency.** Every public `GameHost` method takes one `threading.RLock`. The FastMCP SDK may
  run sync tools on a worker thread, and `GameSession` mutates its state, so the lock is what makes
  the host safe; it does not rely on how the SDK schedules tools. A test calls the host from several
  threads.
- **Memory.** Games are never evicted in this sub-project and there is no `close_game` (YAGNI); the
  process lifetime bounds memory.
- **Output channel.** Nothing may write to stdout (it carries the protocol): logging goes to stderr
  only.

## 5. Tools (MCP surface)

The tool names are the host method names. Each tool returns its view as JSON
(`model_dump(mode="json")`). Arguments are typed so the SDK derives the input schema; descriptions
are written for an LLM (what the tool does, what the handle arguments are, what `nothing_new`,
`locked` and `unknown` mean).

Behaviour is the engine's, unchanged: locations and suspects are known from the start, gated ones
answer `locked`; searching, questioning and records return all newly available facts (at most 4 per
source) or `nothing_new`; calls are idempotent; a discovery lists `opened` sources; a contradiction
appears only when both the lie and its exposer are discovered. An unknown handle to `search`,
`interrogate` or `check_records` is the engine's `unknown` status, not an exception.

### 5.1 Accusation (engine 5.4, steps 3 to 6)

- `nameable(game, axis)` lists the candidates the player may name on `who | how | why` now, with a
  `warned` flag where the player holds a rule-out against the candidate.
- `describe_accusation(game, who?, how?, why?)` builds a `ParsedAccusation` from the handles and
  returns the `AccusationPlan`: resolved names, problems (`unclear` or `not_permitted`, naming what
  may be named instead), soft warnings, the repeat flag, `can_confirm` and the one confirmation line.
- `accuse(game, who, how, why, confirmed)`: the three handles are required strings (the session
  answers `not_permitted` if a part is missing or unknown). It rechecks permission and the
  repeat-triple rule at call time. With `confirmed=false` it consumes no attempt and answers
  `needs_confirmation`. With `confirmed=true` it consumes one attempt and returns only the count of
  correct parts. Three correct is a win, the third miss a loss.

### 5.2 `persona_brief` (new engine code, `play/persona.py`)

`persona_brief(ix, state, suspect_id) -> PersonaBrief` (pure, deterministic), exposed as
`GameSession.persona_brief(suspect_handle)`.

`PersonaBrief` (a `View`, exported from `play` and `gumshoe.cases`, added to `views.py` which imports
nothing from `gumshoe`): `name` (the display name, "<name> the <noun>"), `traits`, `style`, `says`
and `smalltalk_allow`.

- `says`: the fact texts the player **holds** whose source is that suspect's interrogation
  (`SourceRef(INTERROGATE, suspect)`), in neutral order (by text). It is empty until the player
  interrogates the suspect, and after that equals the facts that interrogation returned. It includes
  the suspect's own lie once held. Because held facts are a subset of what `reply_check` allows,
  `says` never contains a token `reply_check` would flag.
- No `reticent` field, no role key, no slot phrases: those either leak the lie's claim or need the
  pack (section 12).
- The shape is identical for every suspect, culprit included, and the culprit's brief comes from the
  same function with no special branch.
- No secret text and no truth field: a secret reaches the player only through its gated record fact.
- A suspect the player has not interrogated gets a brief with empty `says` (not an error); the agent
  can only make small talk. `GameSession.persona_brief` raises `UnknownHandle` for a handle that is not a suspect, and the
  host maps it to `GameError("unknown_handle")`.
- Dialogue itself is the agent loop's job: a paraphrase of `says`, never inventing clues, and always
  passed through `check_reply`.

### 5.3 `check_reply`

Exposes `GameSession.check_reply` as it is: `ReplyCheck(ok, violations)`, with violation categories
(the axis names) and counts, never the offending tokens. An unknown handle is not an exception: the
engine answers `ok=false` with the `unknown_suspect` category, and the tool passes it through.

### 5.4 Saves

- The save file (parsed with a pydantic `SaveFile` model: `save_format: Literal[1]`, `pack: str`,
  `case: str`, `state: str`, no extra keys; a `ValidationError` or `UnicodeDecodeError` is
  `bad_save`) is JSON written to `saves_dir` (constructor argument, default the `GUMSHOE_SAVES`
  environment variable, else `./saves`; the CLI also takes `--saves`):
  `{"save_format": 1, "pack": <name>, "case": <case JSON string>, "state": <state_json string>}`.
  The case already carries the generator, skeleton-algorithm, pack and skin versions.
- `save_game` writes atomically: create the directory if missing, write a temp file in it, then
  `os.replace`. The name is `ids.next()` (drawn again if a file of that name already exists, so a pinned source
  never overwrites a save) and must match `^[0-9a-f]{16}$` (`fullmatch`). `save_game`
  works on a finished game too. It returns a `SaveRef` (name only, never a path).
- `load_game(name)` accepts only a name matching that pattern and resolves it inside `saves_dir`. It
  reads the file and calls `load_session(case_bytes, new_salt, state_json)`. Failures: missing file,
  invalid JSON, wrong `save_format`, or a pydantic `ValidationError` from the case/state are
  `bad_save`; `StateMismatch` (a state that belongs to another case; only possible if the file was
  edited) is `state_mismatch`.
- A loaded game is a **new** game with a new id and a fresh salt, so handles from the original game
  do not work in it. The original game stays in memory until the process ends.
- Saves hold the full skeleton and are spoiler-bearing on disk. No tool takes a path, so the
  directory is not reachable through any tool.
- (Plan 4d-1) `load_game` rebuilds a generated case from its seed and stage counters and
  requires the save's case bytes to equal the rebuild; a case made by another code or pack
  version gets its own `bad_save` message. A save is at most 1 MB, files are 0600, a folder
  holds at most 500 saves, and where the filesystem has no hard links the name is claimed with
  O_EXCL and filled with a rename.

## 6. Errors

Statuses the engine already returns stay statuses: `search`, `interrogate` and `check_records`
answer `unknown`, `locked`, `nothing_new` or `ok` inside `SourceResult`; `check_reply` answers
`unknown_suspect`; `describe_accusation` reports problems in the plan. `unknown_handle` as an
exception is only for `persona_brief` (engine `UnknownHandle`).

One exception, `GameError(code, message)` (named so it cannot be confused with FastMCP's own
`ToolError`). Codes: `unknown_game`, `unknown_handle`, `bad_argument`, `game_over`, `not_over`,
`state_mismatch`, `bad_save`. `GameHost` maps the engine's `GameOver`, `GameNotOver` and
`StateMismatch`.

**Wire format.** The adapters turn a `GameError` into an MCP tool result with `isError = true` and
one text content `"<code>: <message>"`; tests and the agent loop parse that. Any other exception is
a bug: the adapter logs it with a traceback to stderr and returns `"internal_error: the server hit a
bug"`, so no traceback or skeleton field reaches the agent. Task 1 confirms against the installed
SDK that this is how the SDK reports tool failures and adjusts the adapter, not the contract.

## 7. Spoiler rules (checked by tests)

- Every tool result is a `play` view or a type defined in `mcp_server` that carries only values the
  host itself made (`NewGame`, `SaveRef`).
- While the game is playing, no result contains a truth id, the true `(who, how, why)` triple as a
  unit, a `truthful` flag, an effect kind, a skeleton type name, a raw fact id, the text of a secret
  fact the player does not hold, or an ordering that follows generation order. (Labels are not
  forbidden: the true method and motive labels appear in `nameable` options, and the true suspect's
  name is in the brief. A held secret's text appears in `SourceResult` and `notebook`.)
- After a game is over, `reveal` (and `give_up`, which returns a reveal) is the only place the
  truth appears.
- `persona_brief` before the lie is held is byte-identical to the brief for a case whose lie claim
  was changed (the lie's content cannot influence a brief until it is held).

## 8. Tests

1. **Host unit tests** per tool: normal path; `locked`, `nothing_new`, `unknown`; idempotence;
   `unknown_game`; the end-of-game table in section 4 for every tool; `not_over`; argument limits and
   a bad axis; `new_game` with an unknown pack, an unsupported preset and a bad seed.
2. **Property test** (host with pinned ids and salts): random tool-call sequences against generated
   castle cases, all presets. No exception except `GameError`; discovered facts only grow; attempts
   never exceed 3; identical sequences give byte-identical outputs (including a `save_game` in the
   sequence); a non-permitted accusation never consumes an attempt.
3. **Spoiler test:** the full JSON of every tool result over random games contains none of the
   forbidden things in section 7 (truth ids, the triple and the not-yet-held secret texts are taken
   from the case in the test).
4. **`persona_brief` tests:** same field set for every suspect; no secret text; `says` is empty
   before the first interrogation and equals that interrogation's facts afterwards; the suspect's lie
   appears only once held, and right after the first interrogation `says` holds the lie verbatim
   with nothing that marks it apart from the suspect's other statements; the brief is unchanged by
   a changed lie claim until the lie is held (the test builds the changed case with `model_copy` on
   the lie fact's `claim.place` and `text`, not by regenerating; the lie and the motive hint share
   the interrogation source, so "before the lie is held" means "before the first interrogation");
   the culprit has no special branch (same function, same field set).
5. **Accusation tests:** `confirmed=false` consumes nothing; repeat triple; permission rechecked at
   call time; a missing or unknown part is `not_permitted`; count-only feedback; win and loss.
6. **Save and load tests:** round trip; a hand-edited state from another case is `state_mismatch`; a
   corrupt file, a wrong `save_format` and a missing file are `bad_save`; names with `..`, a
   separator or the wrong length are refused; handles from the original game do not work in the
   loaded one; saving a finished game works; the saves directory is created if missing; a salt
   collision is retried (the test forces one by monkeypatching `_make_handles`, since real handles
   are 8 hex digits); a `StateMismatch` or corrupt save is never mistaken for a collision.
7. **Concurrency test:** several threads call the host; no corruption, no exception.
8. **Architecture rules:** `mcp_server` imports follow section 3; the existing outside-`cases`
   rule stays green; `gumshoe.cases` imports nothing from `mcp_server`.
9. **Protocol test:** an in-memory MCP client lists the tools (names and schemas), plays one game to
   a win and one to a loss, and checks the error wire format.
10. **Stdio smoke test:** start `python -m gumshoe.mcp_server`, list tools, start a game, and check
    that stdout holds nothing but protocol messages, including during import (`import gumshoe.cases`
    also loads `gumshoe.decider` through `play/session.py`; the code is decider-free, the process is
    not, so this test is what proves nothing prints).

Existing suites (1666 tests at HEAD) stay green. Changes under `cases/`: `play/persona.py`, the
`PersonaBrief` view, `GameSession.persona_brief`, and the new exports in `play/__init__.py` and
`cases/__init__.py`.

## 9. Tasks (about six)

1. Dependency and skeleton: add `mcp` to `pyproject.toml`; `errors.py`; the new `gumshoe.cases`
   exports (including `HandleCollision`, `UnknownHandle` and the builtin pack loader re-export); `GameHost` with ids, locking, `new_game`,
   `case_brief`; the architecture rules. Verify the SDK's real API (FastMCP import path, tool
   decorator, in-memory client, how errors and sync tools are handled) against the installed
   version before writing adapters; no code depends on a remembered signature.
2. Action tools: `search`, `interrogate`, `check_records`, `notebook`, and their rows of the
   end-of-game table (each later task covers its own rows).
3. Accusation tools: `nameable`, `describe_accusation`, `accuse`, `give_up`, `reveal`.
4. `persona_brief` in the engine (view, function, session method, exports), the host method, and
   `check_reply`.
5. `save_game` and `load_game`.
6. FastMCP adapters (`tools.py`), `__main__`, the protocol, stdio, property, spoiler and
   concurrency tests.

## 10. Out of scope

Jev parsing and routing (sub-project 4); SSE, FastAPI and any HTTP transport (4 and 5); auth and
exposing the server to players (see the trust model); evicting games; any model call; additional
packs (2e); a `reticent` field (section 12).

## 11. Open points to settle in the plan

- The `mcp` SDK version to pin and its exact surface (task 1).
- Whether tool results also carry a short human-readable line (default: no; the JSON is the contract).

## 12. Departure from the parent spec

The parent (engine 5.6) gave `persona_brief` a list of **reticent topics derived from the lie's
claim**. This spec drops it, for three reasons found in review: the claim is the content of a fact
the player has not unlocked (the claimed place and the crime-time phrase, which also gives away the
crime slot); once the lie is in `says`, a matching `reticent` entry identifies which statement is
false, which is the `truthful` distinction the spoiler rules forbid; and liars avoid the scene and
one decoy place, so collecting `reticent` across suspects narrows the field. The brief also drops the
role key and slot phrases (they need the pack, which a `Case` does not carry). If sub-project 4 finds
dialogue needs a deflection hint, it can be built later from every held claim-bearing statement,
true or false alike, so it carries no information about which is the lie.
