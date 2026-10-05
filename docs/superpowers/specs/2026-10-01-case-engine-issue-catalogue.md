# Case engine issue-code catalogue (generated)

| code | group | strict | imported | fix stage | hint | spoiler | needs pack | meaning |
|---|---|---|---|---|---|---|---|---|
| INTERNAL_ERROR | 0 | error | error | none | none |  |  | a rule group crashed on this input |
| BAD_ID | 1 | error | error | assemble | rename_id |  |  | an id does not match the id format |
| COUNT_MISMATCH | 1 | error | error | roster | adjust_count |  |  | an entity count differs from the spec |
| DANGLING_REF | 1 | error | error | assemble | fix_ref |  |  | a reference points at an id that does not exist |
| DUPLICATE_ID | 1 | error | error | assemble | rename_id |  |  | an id is used by more than one entity |
| EFFECT_WRONG_AXIS | 1 | error | error | facts | remove_effect |  |  | an effect names a candidate of a different axis |
| MULTI_AXIS_PROVES | 1 | error | error | facts | remove_effect |  |  | a fact proves on more than one axis |
| SLOTS_TOO_FEW | 1 | error | error | timeline | fix_spec |  |  | the spec has fewer than four time slots |
| SLOT_OUT_OF_RANGE | 1 | error | error | timeline | fix_ref |  |  | a slot is outside 0..spec.slots-1 |
| SOURCE_SHAPE | 1 | error | error | placement | fix_ref |  |  | a source ref has the wrong shape for its kind |
| START_PROVES | 1 | error | error | facts | move_fact |  |  | a fact known from the start proves something |
| TOO_LARGE | 1 | error | error | roster | adjust_count |  |  | the case exceeds the size caps |
| TRACE_KIND_ON_NON_TRACE | 1 | error | error | facts | fix_ref |  |  | a fact that is not a trace names a trace kind |
| TRUTH_NOT_CANDIDATE | 1 | error | error | truth | fix_ref | yes |  | the truth is not among the candidates of its axis |
| UNDECLARED_RECORD_SOURCE | 1 | error | error | placement | fix_ref |  |  | a record source is not declared in the case |
| ALIAS_COLLISION | 2 | error | error | roster | relabel |  |  | an alias collides with another candidate's label or alias |
| LABEL_DUPLICATE | 2 | error | error | roster | relabel |  |  | two candidates have the same normalised label |
| LABEL_LENGTH_SKEW | 2 | error | warning | roster | relabel |  |  | labels on an axis differ too much in length |
| LABEL_NAME_COLLISION | 2 | error | error | roster | relabel |  |  | a method or motive label uses a suspect-name token |
| LABEL_OVERLAP | 2 | error | error | roster | relabel |  |  | two labels on one axis overlap (token subset or substring) |
| NO_DISTINCTIVE_TOKEN | 2 | error | error | roster | relabel |  |  | a candidate has no token no other candidate uses |
| DEPENDENCY_CYCLE | 3 | error | error | gating | break_cycle |  |  | the fact and gate dependencies contain a cycle |
| EMPTY_LOCATION | 4 | error | error | placement | add_fact |  |  | a non-decorative location holds no fact |
| GATE_ON_OWN_LIE | 4 | error | error | gating | break_cycle |  |  | a suspect's record is gated behind that suspect's own lie |
| NO_STATEMENT | 4 | error | error | facts | add_fact |  |  | a suspect has no reachable statement |
| ORPHAN_ENTITY | 4 | error | error | gating | move_fact |  |  | a location, suspect or record source can never be reached |
| ORPHAN_FACT | 4 | error | error | gating | move_fact |  |  | a fact can never be discovered |
| SOURCE_CAP_EXCEEDED | 4 | error | error | placement | move_fact |  |  | a source holds more facts than the cap |
| UNTOUCHABLE_CANDIDATE | 4 | error | error | facts | add_fact |  |  | a candidate has no reachable fact touching it |
| EXPOSER_DEPENDS_ON_LIE | 5 | error | error | gating | break_cycle |  |  | an exposer needs the lie it exposes |
| EXPOSER_IS_LIE | 5 | error | error | facts | add_exposer |  |  | an exposer is itself a lie |
| EXPOSER_MISSING | 5 | error | error | facts | add_exposer |  |  | a lie has no exposer |
| EXPOSER_OWNED_BY_SPEAKER | 5 | error | error | facts | add_exposer |  |  | an exposer comes from the lie's own speaker |
| EXPOSER_UNREACHABLE | 5 | error | error | gating | move_fact |  |  | an exposer can never be discovered |
| HOOK_MISMATCH | 5 | error | error | facts | fix_ref |  |  | the exposure hook does not name an exposer's source |
| LIE_NO_CLAIM | 5 | error | error | facts | add_fact |  |  | a lie has no structured claim |
| LIE_NO_SPEAKER | 5 | error | error | facts | fix_ref |  |  | a lie has no speaker |
| NO_POSITIVE_EVIDENCE | 6 | error | error | facts | add_fact | yes |  | the truth has no non-lie positive evidence |
| NO_ROUTE | 6 | error | error | facts | add_fact | yes |  | there is no proves or elimination route to the truth |
| TRUTH_RULED_OUT | 6 | error | error | facts | remove_effect | yes |  | a truthful fact rules out the truth |
| WRONG_SURVIVES | 6 | error | error | facts | add_fact | yes |  | a wrong candidate is never ruled out |
| ALIBI_NOT_ELSEWHERE | 7 | error | error | facts | fix_ref |  |  | an alibi does not place its subject elsewhere at the crime |
| CLAIM_CONTRADICTS_TIMELINE | 7 | error | error | facts | fix_ref |  |  | a truthful claim disagrees with the timeline |
| CULPRIT_NO_OPPORTUNITY | 7 | error | error | timeline | fix_ref | yes |  | the culprit is not at the scene when the crime happens |
| DOUBLE_BOOKED | 7 | error | error | timeline | fix_ref |  |  | an actor is in two places in one slot |
| LIE_CONSISTENT_WITH_TIMELINE | 7 | error | error | facts | fix_ref |  |  | a lie's claim agrees with the timeline |
| MULTIPLE_CRIME_EVENTS | 7 | error | error | timeline | fix_ref |  |  | the timeline has more than one crime event |
| NO_CRIME_EVENT | 7 | error | error | timeline | add_fact |  |  | the timeline has no crime event |
| OPPORTUNITY_NOT_RULED_OUT | 7 | error | error | facts | add_fact |  |  | an innocent with opportunity has no truthful rule-out |
| ACTIONS_RANGE | 8 | error | error | placement | move_fact |  |  | the cheapest solution's action count is outside the window |
| DECISIVE_RATIO | 8 | error | error | facts | remove_effect |  |  | too large a share of facts is decisive |
| DEPTH_RANGE | 8 | error | error | gating | raise_depth |  |  | the cheapest solution's gating depth is outside the window |
| SINGLE_POINT_OF_FAILURE | 8 | error | warning | facts | add_fact | yes |  | losing one fact makes an axis undecidable |
| SOLUTION_SIZE_RANGE | 8 | error | error | gating | adjust_count |  |  | the cheapest solution is outside the spec's size window |
| CULPRIT_UNIQUE_EXTREME | 9 | error | warning | facts | move_fact | yes |  | the culprit is the unique extreme on a feature |
| EXPOSURES_UNEVEN | 9 | error | warning | facts | add_exposer |  |  | suspects have uneven numbers of exposures |
| FACTS_UNEVEN | 9 | error | warning | placement | move_fact |  |  | suspects own uneven numbers of facts |
| LIES_UNEVEN | 9 | error | warning | facts | add_fact |  |  | suspects have uneven numbers of lies |
| SHAPE_MISMATCH | 9 | error | warning | facts | move_fact |  |  | candidates on an axis have different evidence shapes |
| TRUTH_DEPTH_EXTREME | 9 | error | warning | gating | raise_depth | yes |  | the truth's evidence depth is the unique extreme |
| KNOWS_NOT_SPEAKABLE | 10 | error | error | facts | fix_ref |  |  | a suspect knows a fact they cannot speak |
| MOTIVE_MAPPING | 10 | error | error | roster | fix_ref |  |  | suspects do not map one-to-one onto motives |
| SECRET_FACT_MISSING | 10 | error | error | facts | add_fact |  |  | a suspect has no secret fact |
| SECRET_SOURCE_MISMATCH | 10 | error | error | placement | move_fact |  |  | a secret fact is not a record about its suspect |
| CLAIM_SUBJECT_MISMATCH | 11 | error | error | facts | fix_ref |  | yes | a record claim is about a suspect but the pack's record kind has another subject |
| LOCATION_KIND_NOT_IN_PACK | 11 | error | error | roster | fix_pack |  | yes | a location's kind is not defined by the pack |
| LOCATION_KIND_NOT_IN_SCENE | 11 | error | error | roster | fix_pack |  | yes | the crime location's kind is not allowed at the scene type |
| PACK_CAPACITY | 11 | error | error | pack | adjust_count |  | yes | a count exceeds the pack's capacity |
| PACK_MISMATCH | 11 | error | error | pack | fix_pack |  | yes | the case's pack reference does not match the supplied pack |
| PACK_RULES_SKIPPED | 11 | error | info | none | none |  |  | pack-bound rules were skipped because no pack was supplied |
| PACK_SOURCE_KIND_CAPACITY | 11 | error | error | placement | move_fact |  | yes | a source kind is overloaded relative to its sources |
| RECORD_KIND_NOT_IN_PACK | 11 | error | error | pack | fix_pack |  | yes | a record source or claim uses a record kind the pack does not define |
| RECORD_SUBJECT_MISMATCH | 11 | error | error | facts | fix_pack |  | yes | a record source's subject type does not match the pack's record kind |
| ROLE_MOTIVE_NOT_ALLOWED | 11 | error | error | roster | fix_pack |  | yes | a suspect's motive type is not allowed for their role |
| ROLE_RECORD_KIND_NOT_ALLOWED | 11 | error | error | roster | fix_pack |  | yes | a suspect's secret record kind is not allowed for their role |
| ROLE_UNKNOWN | 11 | error | error | roster | fix_pack |  | yes | a suspect's role is not defined by the pack |
| SCENE_METHOD_NOT_ALLOWED | 11 | error | error | roster | drop_candidate |  | yes | a method is not possible at the scene type |
| SCENE_NOT_IN_PACK | 11 | error | error | pack | fix_pack |  | yes | the scene type is not defined by the pack |
| SPEC_MISMATCH | 11 | error | error | pack | fix_spec |  | yes | the case's spec is not the one derived from its preset and pack |
| TRACE_KIND_MISSING | 11 | error | error | facts | fix_ref |  | yes | a trace fact names no trace kind |
| TRACE_KIND_NOT_ALLOWED | 11 | error | error | facts | fix_pack |  | yes | a trace kind is not allowed at the scene type or at the place it is found |
