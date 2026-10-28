"""The bundled packs a player can choose, checked once. A pack that fails stops startup."""

from collections.abc import Mapping
from functools import cache
from importlib.resources import files
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel, ConfigDict

from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.spec import PRESETS
from gumshoe.cases.packs.check.capacity import hosted_specs
from gumshoe.cases.tools.builtin import BuiltinPackError, load_builtin_pack

DEFAULT_PACK: Final = "castle"


class PackInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    blurb: str
    presets: tuple[str, ...]  # the presets the pack claims, not every one the spec accepts


def _stems() -> list[str]:
    # *.toml stems only, so "__init__" or "loader" can never name a pack
    return sorted(
        p.name.removesuffix(".toml")
        for p in files("gumshoe.cases.packs").iterdir()
        if p.name.endswith(".toml")
    )


def _info_for(stem: str, pack: Pack) -> PackInfo:
    if pack.id != stem:
        raise BuiltinPackError(f"bundled pack {stem!r} declares id {pack.id!r}")
    if not (pack.title and pack.title.strip()):
        raise BuiltinPackError(f"bundled pack {stem!r} has no title")
    if not (pack.blurb and pack.blurb.strip()):
        raise BuiltinPackError(f"bundled pack {stem!r} has no blurb")
    presets = tuple(n for n, _ in hosted_specs(pack, PRESETS))
    if "standard" not in presets:
        raise BuiltinPackError(f"bundled pack {stem!r} does not claim the standard preset")
    return PackInfo(id=stem, title=pack.title, blurb=pack.blurb, presets=presets)


def _build() -> tuple[tuple[PackInfo, ...], Mapping[str, Pack]]:
    """Load and check every bundled pack. Uncached, so tests can patch its inputs."""
    loaded = {stem: load_builtin_pack(stem) for stem in sorted(_stems())}
    infos = tuple(_info_for(stem, pack) for stem, pack in loaded.items())
    if DEFAULT_PACK not in loaded:
        raise BuiltinPackError(f"the default pack {DEFAULT_PACK!r} is not bundled")
    return infos, MappingProxyType(loaded)


# one cached result holding both views, so no reader can see one without the other
_load = cache(_build)


def bundled_packs() -> tuple[PackInfo, ...]:
    return _load()[0]


def bundled_pack(pack_id: str) -> Pack | None:
    return _load()[1].get(pack_id)


def pack_info(pack_id: str) -> PackInfo | None:
    return next((i for i in bundled_packs() if i.id == pack_id), None)
