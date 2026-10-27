# Pack issue-code catalogue (generated)

| code | stage | severity | meaning |
|---|---|---|---|
| MISSING_FIELD | 1 | error | required field {field!r} is missing |
| TOML_SYNTAX | 1 | error | the file is not valid TOML: {reason} |
| UNKNOWN_KEY | 1 | error | unknown key {key!r} |
| WRONG_TYPE | 1 | error | wrong type or value: {reason} |
| DUPLICATE_KEY | 2 | error | the key {name!r} is defined more than once |
| UNKNOWN_LOCATION_KIND | 2 | error | unknown location kind {name!r} |
| UNKNOWN_METHOD | 2 | error | unknown method {name!r} |
| UNKNOWN_MOTIVE_TYPE | 2 | error | unknown motive type {name!r} |
| UNKNOWN_RECORD_KIND | 2 | error | unknown record kind {name!r} |
| UNKNOWN_TRACE_KIND | 2 | error | unknown trace kind {name!r} |
| ARTICLE_MISMATCH | 3 | error | 'a' or 'an' does not fit the next word ({phrase!r}) |
| CLAIM_SLOT_MISSING | 3 | error | a variant lacks the claim slot {slot!r} |
| DOUBLED_WORD | 3 | error | doubled word {word!r} in the rendered text |
| DOUBLE_SPACE | 3 | error | two spaces in a row in the rendered text |
| MID_SENTENCE_CAPITAL | 3 | error | capitalised word {word!r} inside a sentence; use a placeholder for names |
| TOO_FEW_VARIANTS | 3 | error | family has {count} variants; needs at least {needed} |
| UNKNOWN_PLACEHOLDER | 3 | error | unknown placeholder {name!r} |
| UNRESOLVED_BRACE | 3 | error | unbalanced or unresolved brace in the text |
| DUPLICATE_ENTRY | 4 | error | the list names {value!r} more than once |
| LABEL_TOKEN_LEAK | 4 | error | this text uses the token {token!r}, distinctive to candidate {candidate!r} |
| NAME_DUPLICATE | 4 | error | the name {name!r} equals {other!r} (same text after Unicode normalisation and case) |
| RECORD_KEY_INVALID | 4 | error | the record kind key {key!r} must be lowercase letters, digits and underscores (1 to 30) |
| ROLE_NO_NAME | 4 | error | the role has no name to give a suspect |
| SECRET_REUSES_LABEL | 4 | error | the secret of {candidate!r} reuses its own label token {token!r} |
| TRACE_COUNT_SKEW | 4 | error | this method has {count} trace templates; the largest count is {target} |
| TRACE_LENGTH_SKEW | 4 | error | mean trace length {mean} is more than 20% from the overall mean {overall} |
| METHOD_TOO_RARE | 5 | error | the method is allowed in {count} scene types; needs at least {needed} |
| MOTIVE_UNREACHABLE | 5 | error | no role allows this motive type |
| RECORD_EVENT_SUBJECT | 5 | error | the record kind is about an event; the generator supports suspects and places only |
| ROLE_NO_RECORD_KIND | 5 | error | the role has no record kind |
| ROLE_NO_SUSPECT_RECORD | 5 | error | the role has no record kind about a suspect |
| ROLE_TOO_FEW_MOTIVES | 5 | error | the role allows {count} motive types; needs at least {needed} |
| SCENE_MANY_CRIME_LOCATIONS | 5 | error | the scene type lists {count} location kinds; the generator needs exactly one |
| SCENE_METHOD_IMPOSSIBLE | 5 | error | no trace of method {method!r} can be placed at scene type {scene!r} |
| SCENE_NO_CRIME_LOCATION | 5 | error | the scene type has no location kind for the crime |
| SLOT_DEFS_TOO_FEW | 5 | error | {defs} slot definitions for {slots} slots |
| CAPACITY_EXCEEDS_POOL | 6 | error | capacity allows {capacity} {what} but the pack defines only {pool} |
| LOCATION_KINDS_TOO_FEW | 6 | error | the pack defines {count} location kinds; needs at least {needed} |
| PRESET_NOT_MONOTONE | 6 | error | effective {size} drops from preset {previous!r} to {preset!r} |
| PRESET_NO_DEPTH | 6 | error | no gating depth fits the {preset!r} preset on this pack (record kinds, windows or source capacity rule out every depth) |
| PRESET_UNSUPPORTED | 6 | error | the pack cannot host this preset: {reason} |
| MOTIVE_TOO_PREDICTABLE | 7 | error | in roster {roster} this role gets this motive {percent}% of the time; the cap is 50% |
| NO_PERFECT_MATCHING | 7 | error | no suspect-to-motive matching exists for roster {roster} |
| ROSTER_INFEASIBLE | 7 | error | the {preset!r} preset can draw a roster the generator cannot build: {reason} |

## Roster walk (stage 7)

`ROSTER_INFEASIBLE` comes from a walk of every roster the generator could draw for each claimed
preset. The walk's work is counted in units (one per draw, per visited record-kind subset and per
location-subset check) against `ROSTER_CHECK_BUDGET = 1_000_000`. A preset whose walk would exceed
the budget is reported as `PRESET_UNSUPPORTED` ("roster check too large").

## Known gaps

The roster walk deliberately does not model two failures:

- `spec.locations < 3` always fails in the facts stage ("no non-scene place to lie about"). It
  cannot happen with the real `PRESETS` (minimum 3), but the test presets can have 2.
- Placement fails ("no location with room") when more than `source_cap` (4) of the chosen methods
  have traces that fit only one chosen place. The generator's retry absorbs most cases.
