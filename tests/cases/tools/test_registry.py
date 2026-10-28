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


def _patch(monkeypatch, stems, packs):
    monkeypatch.setattr(registry, "_stems", lambda: stems)
    monkeypatch.setattr(registry, "load_builtin_pack", lambda stem: packs[stem])


def _castle(**update):
    return load_builtin_pack("castle").model_copy(update=update)


def test_presets_are_the_ones_the_pack_claims(monkeypatch):
    assert "long" in pack_info("castle").presets  # type: ignore[union-attr]
    _patch(monkeypatch, ["castle"], {"castle": _castle(presets=("short", "standard"))})
    infos, packs = registry._build()
    assert infos[0].presets == ("short", "standard")
    assert packs["castle"].id == "castle"


def test_rows_are_sorted_by_id_whatever_the_listing_order(monkeypatch):
    packs = {
        "castle": _castle(),
        "alpha": _castle(id="alpha"),
        "zed": _castle(id="zed"),
    }
    _patch(monkeypatch, ["zed", "castle", "alpha"], packs)
    infos, _ = registry._build()
    assert [i.id for i in infos] == ["alpha", "castle", "zed"]


@pytest.mark.parametrize("name", ["nope", "", "__init__", "../castle", "catalogue"])
def test_only_bundled_toml_stems_resolve(name):
    assert pack_info(name) is None
    assert bundled_pack(name) is None


@pytest.mark.parametrize(
    ("stems", "update", "word"),
    [
        (["castle", "other"], {}, "declares id"),
        (["castle"], {"title": None}, "no title"),
        (["castle"], {"title": "  "}, "no title"),
        (["castle"], {"blurb": "  "}, "no blurb"),
        (["castle"], {"presets": ("short",)}, "standard"),
    ],
)
def test_a_broken_registry_is_refused(monkeypatch, stems, update, word):
    packs = {s: _castle(title="T", blurb="B") for s in stems}
    packs[stems[-1]] = packs[stems[-1]].model_copy(update=update)
    _patch(monkeypatch, stems, packs)
    with pytest.raises(BuiltinPackError, match=rf"{stems[-1]}.*{word}"):
        registry._build()


def test_a_set_without_the_default_pack_is_refused(monkeypatch):
    _patch(monkeypatch, ["other"], {"other": _castle(id="other", title="T", blurb="B")})
    with pytest.raises(BuiltinPackError, match="default pack 'castle'"):
        registry._build()


def test_a_stem_that_is_not_an_identifier_is_refused(monkeypatch):
    monkeypatch.setattr(registry, "_stems", lambda: ["my-pack"])
    with pytest.raises(BuiltinPackError, match="my-pack"):
        registry._build()
