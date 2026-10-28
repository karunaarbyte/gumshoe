import pytest

from gumshoe.cases import (
    DEFAULT_PACK,
    BuiltinPackError,
    bundled_pack,
    bundled_packs,
    load_builtin_pack,
    pack_info,
)
from gumshoe.cases.tools import registry


def test_the_castle_is_registered_with_title_blurb_and_standard():
    rows = {r.id: r for r in bundled_packs()}
    castle = rows[DEFAULT_PACK]
    assert castle.title and castle.blurb
    assert "standard" in castle.presets
    assert [r.id for r in bundled_packs()] == sorted(rows)
    assert bundled_pack("castle") is not None
    assert bundled_pack("castle").id == "castle"  # type: ignore[union-attr]
    assert bundled_pack("nope") is None


def test_presets_are_the_ones_the_pack_claims():
    pack = load_builtin_pack("castle")
    assert pack_info("castle") is not None
    assert "long" in pack_info("castle").presets  # type: ignore[union-attr]
    narrow = pack.model_copy(update={"presets": ("short", "standard")})
    assert registry._info_for("castle", narrow).presets == ("short", "standard")


@pytest.mark.parametrize("name", ["nope", "", "__init__", "../castle", "catalogue"])
def test_only_bundled_toml_stems_resolve(name):
    assert pack_info(name) is None
    assert bundled_pack(name) is None


def _broken(monkeypatch, stems, **update):
    pack = load_builtin_pack("castle")

    def fake_load(stem):
        return pack.model_copy(update=update)

    monkeypatch.setattr(registry, "_stems", lambda: stems)
    monkeypatch.setattr(registry, "load_builtin_pack", fake_load)


@pytest.mark.parametrize(
    ("stems", "update"),
    [
        (["castle", "other"], {}),  # id castle under stem other
        (["castle"], {"title": None}),
        (["castle"], {"blurb": "  "}),
        (["castle"], {"presets": ("short",)}),
    ],
)
def test_a_broken_registry_is_refused(monkeypatch, stems, update):
    _broken(monkeypatch, stems, **{"title": "T", "blurb": "B", **update})
    with pytest.raises(BuiltinPackError) as err:
        registry.bundled_packs.__wrapped__()
    assert stems[-1] in str(err.value)


def test_a_set_without_the_default_pack_is_refused(monkeypatch):
    pack = load_builtin_pack("castle")
    other = pack.model_copy(update={"id": "other", "title": "T", "blurb": "B"})
    monkeypatch.setattr(registry, "_stems", lambda: ["other"])
    monkeypatch.setattr(registry, "load_builtin_pack", lambda stem: other)
    with pytest.raises(BuiltinPackError, match="castle"):
        registry.bundled_packs.__wrapped__()
