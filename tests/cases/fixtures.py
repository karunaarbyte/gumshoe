"""manor_small: the hand-built known-good case (profile `custom`), its tiny Pack, strict variant."""

from gumshoe.cases.model.case import Case
from gumshoe.cases.model.entities import (
    Claim,
    Effect,
    Event,
    Fact,
    Limits,
    Location,
    Method,
    Motive,
    PackRef,
    RecordSource,
    SourceRef,
    Spec,
    Start,
    Suspect,
    Truth,
)
from gumshoe.cases.model.enums import (
    Axis,
    ClaimKind,
    EffectKind,
    FactKind,
    Origin,
    RecordSubjectType,
    SourceKind,
)
from gumshoe.cases.model.pack import (
    Capacity,
    LocationDef,
    MethodDef,
    Pack,
    RecordDef,
    RoleDef,
    SceneType,
    TraceDef,
)
from gumshoe.cases.model.spec import PresetDef, SizeRange

RULES_OUT, SUPPORTS, PROVES = EffectKind.RULES_OUT, EffectKind.SUPPORTS, EffectKind.PROVES
WHO, HOW, WHY = Axis.WHO, Axis.HOW, Axis.WHY

LIMITS = Limits(
    solution_min=3,
    solution_max=12,
    depth_min=0,
    depth_max=3,
    actions_min=2,
    actions_max=8,
    decisive_pct_max=30,
)


def search(location: str) -> SourceRef:
    return SourceRef(kind=SourceKind.SEARCH, target=location)


def ask(suspect: str) -> SourceRef:
    return SourceRef(kind=SourceKind.INTERROGATE, target=suspect)


def record(kind: str, subject: str) -> SourceRef:
    return SourceRef(kind=SourceKind.RECORD, target=kind, subject=subject)


def eff(axis: Axis, candidate: str, kind: EffectKind) -> Effect:
    return Effect(axis=axis, candidate=candidate, kind=kind)


def presence(actor: str, place: str, slot: int) -> Claim:
    return Claim(kind=ClaimKind.PRESENCE, actor=actor, slot=slot, place=place)


def build_facts() -> tuple[Fact, ...]:
    return (
        # search(l_garden)
        Fact(
            id="f_key",
            kind=FactKind.CLUE,
            source=search("l_garden"),
            text="A brass key lies under the garden bench.",
        ),
        Fact(
            id="f_alibi_anna",
            kind=FactKind.ALIBI,
            source=search("l_garden"),
            effects=(eff(WHO, "s_anna", RULES_OUT),),
            claim=presence("s_anna", "l_garden", 2),
            timeline_ref=("t_anna_2",),
            text="The gardener swears Anna was among the roses when the bell rang.",
        ),
        # search(l_study)
        Fact(
            id="f_proof_boris",
            kind=FactKind.PRESENCE,
            source=search("l_study"),
            effects=(eff(WHO, "s_boris", PROVES),),
            claim=presence("s_boris", "l_study", 2),
            timeline_ref=("t_crime",),
            text="Boris's monogrammed cufflink lies beside the body.",
        ),
        Fact(
            id="f_trace_poison",
            kind=FactKind.TRACE,
            trace_kind="residue",
            source=search("l_study"),
            effects=(eff(HOW, "m_poison", PROVES),),
            text="Bitter residue in the glass matches the poison kept in the cellar.",
        ),
        Fact(
            id="f_absent_dagger",
            kind=FactKind.ABSENT_TRACE,
            trace_kind="wound",
            source=search("l_study"),
            effects=(eff(HOW, "m_dagger", RULES_OUT),),
            text="There is no wound on the body.",
        ),
        Fact(
            id="f_absent_rope",
            kind=FactKind.ABSENT_TRACE,
            trace_kind="fibre",
            source=search("l_study"),
            effects=(eff(HOW, "m_rope", RULES_OUT),),
            text="There are no marks on the neck.",
        ),
        # search(l_cellar)  (gated by f_key)
        Fact(
            id="f_clara_keys",
            kind=FactKind.PHYSICAL,
            source=search("l_cellar"),
            effects=(eff(WHO, "s_clara", RULES_OUT),),
            text=(
                "Clara's keyring hangs on the cellar hook; "
                "she never held the cellar key to fetch the poison."
            ),
        ),
        # interrogate: each suspect's lie, and a truthful remark about someone else
        Fact(
            id="f_lie_anna",
            kind=FactKind.LIE,
            source=ask("s_anna"),
            speaker="s_anna",
            truthful=False,
            claim=presence("s_anna", "l_cellar", 2),
            effects=(eff(WHO, "s_anna", RULES_OUT),),
            exposed_by=("f_secret_anna",),
            exposure_hook=record("ledger", "s_anna"),
            timeline_ref=("t_anna_2",),
            text="I was down in the cellar all evening.",
            contradiction="Anna says the cellar, but the ledger places her in the garden.",
        ),
        Fact(
            id="f_sup_boris",
            kind=FactKind.WITNESS,
            source=ask("s_anna"),
            speaker="s_anna",
            effects=(eff(WHO, "s_boris", SUPPORTS),),
            text="I saw Boris heading for the study.",
        ),
        Fact(
            id="f_lie_boris",
            kind=FactKind.LIE,
            source=ask("s_boris"),
            speaker="s_boris",
            truthful=False,
            claim=presence("s_boris", "l_garden", 2),
            effects=(eff(WHO, "s_boris", RULES_OUT),),
            exposed_by=("f_secret_boris",),
            exposure_hook=record("ledger", "s_boris"),
            timeline_ref=("t_crime",),
            text="I was walking in the garden.",
            contradiction="Boris claims the garden, but the ledger puts him at the study.",
        ),
        Fact(
            id="f_sup_clara",
            kind=FactKind.WITNESS,
            source=ask("s_boris"),
            speaker="s_boris",
            effects=(eff(WHO, "s_clara", SUPPORTS),),
            text="Clara never hid how she hated him.",
        ),
        Fact(
            id="f_lie_clara",
            kind=FactKind.LIE,
            source=ask("s_clara"),
            speaker="s_clara",
            truthful=False,
            claim=presence("s_clara", "l_cellar", 2),
            effects=(eff(WHO, "s_clara", RULES_OUT),),
            exposed_by=("f_secret_clara",),
            exposure_hook=record("ledger", "s_clara"),
            timeline_ref=("t_clara_2",),
            text="I was fetching wine from the cellar.",
            contradiction="Clara says the cellar, but the ledger shows her at the study.",
        ),
        Fact(
            id="f_sup_anna",
            kind=FactKind.WITNESS,
            source=ask("s_clara"),
            speaker="s_clara",
            effects=(eff(WHO, "s_anna", SUPPORTS),),
            text="Anna quarrelled with him that afternoon.",
        ),
        # record(ledger, suspect): the secret, which also exposes that suspect's lie
        Fact(
            id="f_secret_anna",
            kind=FactKind.SECRET,
            source=record("ledger", "s_anna"),
            effects=(eff(WHY, "v_jealousy", SUPPORTS),),
            claim=presence("s_anna", "l_garden", 2),
            timeline_ref=("t_anna_2",),
            text="Letters in the ledger show Anna's jealous devotion.",
        ),
        Fact(
            id="f_secret_boris",
            kind=FactKind.SECRET,
            source=record("ledger", "s_boris"),
            effects=(eff(WHY, "v_debt", PROVES),),
            claim=presence("s_boris", "l_study", 2),
            timeline_ref=("t_crime",),
            text="The ledger shows Boris owes a ruinous gambling debt.",
        ),
        Fact(
            id="f_secret_clara",
            kind=FactKind.SECRET,
            source=record("ledger", "s_clara"),
            effects=(eff(WHY, "v_inheritance", SUPPORTS),),
            claim=presence("s_clara", "l_study", 2),
            timeline_ref=("t_clara_2",),
            text="A will in the ledger names Clara as an heir.",
        ),
        # record(gate_log, l_study): why-axis clues
        Fact(
            id="f_ruleout_jealousy",
            kind=FactKind.MOTIVE_CLUE,
            source=record("gate_log", "l_study"),
            effects=(eff(WHY, "v_jealousy", RULES_OUT),),
            text="The victim had no entanglements at all.",
        ),
        Fact(
            id="f_ruleout_inheritance",
            kind=FactKind.MOTIVE_CLUE,
            source=record("gate_log", "l_study"),
            effects=(eff(WHY, "v_inheritance", RULES_OUT),),
            text="The victim's estate passes to the crown.",
        ),
        Fact(
            id="f_sup_debt",
            kind=FactKind.MOTIVE_CLUE,
            source=record("gate_log", "l_study"),
            effects=(eff(WHY, "v_debt", SUPPORTS),),
            text="A moneylender's note was pinned to the door.",
        ),
        # record(gate_log, l_garden): how-axis supports
        Fact(
            id="f_sup_poison",
            kind=FactKind.TRACE,
            trace_kind="residue",
            source=record("gate_log", "l_garden"),
            effects=(eff(HOW, "m_poison", SUPPORTS),),
            text="Wine was carried up from the cellar.",
        ),
        Fact(
            id="f_sup_dagger",
            kind=FactKind.PHYSICAL,
            source=record("gate_log", "l_garden"),
            effects=(eff(HOW, "m_dagger", SUPPORTS),),
            text="A letter opener went missing from the desk.",
        ),
        Fact(
            id="f_sup_rope",
            kind=FactKind.PHYSICAL,
            source=record("gate_log", "l_garden"),
            effects=(eff(HOW, "m_rope", SUPPORTS),),
            text="A coil of rope hung by the door.",
        ),
    )


def custom_spec() -> Spec:
    return Spec(
        preset="custom",
        suspects=3,
        methods=3,
        motives=3,
        locations=3,
        record_kinds=2,
        slots=4,
        opportunity=1,
        limits=LIMITS,
    )


def build_case() -> Case:
    return Case(
        id="c_manor_small",
        theme="manor",
        spec=custom_spec(),
        scene_type="study_murder",
        truth=Truth(who="s_boris", how="m_poison", why="v_debt"),
        start=Start(
            locations=("l_study", "l_garden"), suspects=("s_anna", "s_boris", "s_clara"), facts=()
        ),
        suspects=(
            Suspect(
                id="s_anna",
                label="Anna the maid",
                aliases=("Anna", "the maid"),
                role="maid",
                motive="v_jealousy",
                secret_fact="f_secret_anna",
                knows=("f_lie_anna", "f_sup_boris"),
                display_name="Anna",
                description="The upstairs maid.",
                traits=("anxious",),
                style="quick and nervous",
                secret_text="Anna adored the master.",
            ),
            Suspect(
                id="s_boris",
                label="Boris the steward",
                aliases=("Boris", "the steward"),
                role="steward",
                motive="v_debt",
                secret_fact="f_secret_boris",
                knows=("f_lie_boris", "f_sup_clara"),
                display_name="Boris",
                description="The household steward.",
                traits=("precise",),
                style="formal",
                secret_text="Boris gambles beyond his means.",
            ),
            Suspect(
                id="s_clara",
                label="Clara the cook",
                aliases=("Clara", "the cook"),
                role="cook",
                motive="v_inheritance",
                secret_fact="f_secret_clara",
                knows=("f_lie_clara", "f_sup_anna"),
                display_name="Clara",
                description="The cook.",
                traits=("blunt",),
                style="gruff",
                secret_text="Clara stands to inherit.",
            ),
        ),
        locations=(
            Location(
                id="l_study", kind="study", name="The study", description="Books and a cold hearth."
            ),
            Location(id="l_garden", kind="garden", name="The garden", description="Wet roses."),
            Location(
                id="l_cellar",
                kind="cellar",
                requires=("f_key",),
                name="The cellar",
                description="Damp stone and shelves.",
            ),
        ),
        record_sources=(
            RecordSource(kind="ledger", subject_type=RecordSubjectType.SUSPECT, subject="s_anna"),
            RecordSource(kind="ledger", subject_type=RecordSubjectType.SUSPECT, subject="s_boris"),
            RecordSource(kind="ledger", subject_type=RecordSubjectType.SUSPECT, subject="s_clara"),
            RecordSource(
                kind="gate_log", subject_type=RecordSubjectType.LOCATION, subject="l_study"
            ),
            RecordSource(
                kind="gate_log", subject_type=RecordSubjectType.LOCATION, subject="l_garden"
            ),
        ),
        methods=(
            Method(
                id="m_poison",
                label="poisoned in the wine",
                aliases=("poison", "laced wine"),
                type="poison",
            ),
            Method(
                id="m_dagger",
                label="stabbed with a dagger",
                aliases=("knife", "blade"),
                type="dagger",
            ),
            Method(
                id="m_rope", label="strangled with a rope", aliases=("rope", "garrote"), type="rope"
            ),
        ),
        motives=(
            Motive(
                id="v_debt",
                label="to cover a gambling debt",
                aliases=("debt", "money owed"),
                type="debt",
            ),
            Motive(
                id="v_jealousy",
                label="out of jealousy",
                aliases=("jealous", "envy"),
                type="jealousy",
            ),
            Motive(
                id="v_inheritance",
                label="to claim an inheritance",
                aliases=("inherit", "legacy"),
                type="inheritance",
            ),
        ),
        timeline=(
            Event(id="t_crime", slot=2, actor="s_boris", place="l_study", action="crime"),
            Event(id="t_anna_2", slot=2, actor="s_anna", place="l_garden", action="present"),
            Event(id="t_clara_2", slot=2, actor="s_clara", place="l_study", action="present"),
        ),
        facts=build_facts(),
        intro="A winter evening at the manor; the master lies dead in his study.",
        smalltalk_allow=("evening", "weather"),
    )


# -- the tiny pack and a strict variant ------------------------------------------------------

TINY_PRESETS = {
    "tiny": PresetDef(
        name="tiny",
        suspects=SizeRange(min=3, max=3),
        methods=SizeRange(min=3, max=3),
        locations=SizeRange(min=3, max=3),
        record_kinds=SizeRange(min=2, max=2),
        slots=4,
        opportunity=1,
        limits=LIMITS,
    )
}


def build_pack() -> Pack:
    motive_types = ("debt", "inheritance", "jealousy")
    all_places = ("cellar", "garden", "study")

    def method(key: str, label: str, kind: str) -> MethodDef:
        return MethodDef(
            key=key,
            label=label,
            traces=(TraceDef(kind=kind, location_kinds=all_places),),
        )

    return Pack(
        id="tiny",
        capacity=Capacity(max_suspects=3, max_locations=3, max_methods=3, max_record_kinds=2),
        presets=("tiny",),
        scene_types=(
            SceneType(
                key="study_murder",
                location_kinds=("study",),
                allowed_methods=("dagger", "poison", "rope"),
                allowed_trace_kinds=("fibre", "residue", "wound"),
            ),
        ),
        roles=(
            RoleDef(key="maid", record_kinds=("ledger",), motive_types=motive_types),
            RoleDef(key="steward", record_kinds=("ledger",), motive_types=motive_types),
            RoleDef(key="cook", record_kinds=("ledger",), motive_types=motive_types),
        ),
        record_kinds=("gate_log", "ledger"),
        location_defs=tuple(LocationDef(key=k) for k in all_places),
        record_defs=(
            RecordDef(key="gate_log", subject="location", medium="written"),
            RecordDef(key="ledger", subject="suspect", medium="written"),
        ),
        method_defs=(
            method("dagger", "stabbed with a dagger", "wound"),
            method("poison", "poisoned in the wine", "residue"),
            method("rope", "strangled with a rope", "fibre"),
        ),
    )


def build_strict_case() -> Case:
    from gumshoe.cases.model.spec import derive_spec

    pack = build_pack()
    return build_case().model_copy(
        update={
            "spec": derive_spec("tiny", pack, TINY_PRESETS),
            "origin": Origin.GENERATED,
            "pack_ref": PackRef(id=pack.id, skeleton_hash=pack.skeleton_hash()),
            "skin_rev": 1,
        }
    )
