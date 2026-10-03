"""The packs bundled with the package: the only place that reads them from disk."""

from importlib.resources import files

from gumshoe.cases.model.pack import Pack
from gumshoe.cases.packs import load_pack


class BuiltinPackError(Exception):
    """A bundled pack is missing or does not pass its own checks."""


def load_builtin_pack(name: str) -> Pack:
    # a plain identifier only: a path such as "../x" or "/abs/x" must never reach the lookup
    if not (isinstance(name, str) and name.isidentifier()):
        raise BuiltinPackError(f"{name!r} is not a bundled pack name (a plain identifier)")
    try:
        data = files("gumshoe.cases.packs").joinpath(f"{name}.toml").read_bytes()
    except OSError as exc:
        raise BuiltinPackError(f"no bundled pack named {name!r}") from exc
    result = load_pack(data)
    if not result.ok or result.pack is None:
        first = result.issues[0] if result.issues else None
        raise BuiltinPackError(
            f"pack {name!r} has {len(result.issues)} issue(s)"
            + (f"; first: {first.code} at {first.path}" if first else "")
        )
    return result.pack
