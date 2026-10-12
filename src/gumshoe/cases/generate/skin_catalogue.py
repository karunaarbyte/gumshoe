"""Every code `skin_lint` can report, declared once. Names are plain and collide with no case or
pack code (a test enforces it); every one is fixed by drawing the skin again."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SkinIssue:
    code: str
    path: str  # such as facts.<id>.text or suspects.<id>.display_name
    message: str


@dataclass(frozen=True)
class SkinCode:
    message: str  # str.format template over `params`
    params: tuple[str, ...]


SKIN_CATALOGUE: dict[str, SkinCode] = {
    "LEAK_TOKEN": SkinCode(
        "the text uses {token!r}, a token of {candidate}, but does not touch it",
        ("token", "candidate"),
    ),
    "LABEL_NOT_IN_NAME": SkinCode(
        "the display name lacks {token!r}, a distinctive token of the label", ("token",)
    ),
    "DUPLICATE_SENTENCE": SkinCode("the text equals the one at {other}", ("other",)),
    "CLAIM_VALUE_MISSING": SkinCode(
        "the text lacks {what} ({value!r}) that the fact claims", ("what", "value")
    ),
    "CONTRADICTION_MISSING": SkinCode(
        "the lie has no contradiction that names {value!r}", ("value",)
    ),
    "BLANK_TEXT": SkinCode("a text the case needs is empty", ()),
    "BAD_RENDER": SkinCode("the rendered text has {problem}", ("problem",)),
}


def make(code: str, path: str, **params: object) -> SkinIssue:
    spec = SKIN_CATALOGUE[code]  # KeyError for an unknown code: checks cannot invent codes
    if set(params) != set(spec.params):
        raise ValueError(f"{code} takes {spec.params}, got {sorted(params)}")
    return SkinIssue(code, path, spec.message.format(**params))
