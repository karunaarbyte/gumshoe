from enum import StrEnum


class Axis(StrEnum):
    WHO = "who"
    HOW = "how"
    WHY = "why"


class EffectKind(StrEnum):
    RULES_OUT = "rules_out"
    SUPPORTS = "supports"
    PROVES = "proves"


class SourceKind(StrEnum):
    SEARCH = "search"
    INTERROGATE = "interrogate"
    RECORD = "record"


class RecordSubjectType(StrEnum):
    SUSPECT = "suspect"
    LOCATION = "location"
    EVENT = "event"


class FactKind(StrEnum):
    ALIBI = "alibi"
    PRESENCE = "presence"
    WITNESS = "witness"
    LIE = "lie"
    TRACE = "trace"
    ABSENT_TRACE = "absent_trace"
    PHYSICAL = "physical"
    SECRET = "secret"
    MOTIVE_CLUE = "motive_clue"
    CLUE = "clue"


class ClaimKind(StrEnum):
    PRESENCE = "presence"
    RECORD_REF = "record_ref"


class Origin(StrEnum):
    GENERATED = "generated"
    IMPORTED = "imported"


class Medium(StrEnum):
    WRITTEN = "written"
    TOKEN = "token"
    ORAL = "oral"
