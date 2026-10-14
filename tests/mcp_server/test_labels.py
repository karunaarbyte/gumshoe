"""Record kinds are named the way the case text names them (the pack's display names)."""

import pytest

from gumshoe.cases import load_builtin_pack
from tests.mcp_server.helpers import explore_all, make_host

DISPLAY = {d.key: d.names[0].text for d in load_builtin_pack("castle").record_defs}


def test_the_castle_pack_names_a_record_kind_differently_from_its_key():
    assert DISPLAY["chapel_register"] == "household register"


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_record_kinds_and_sources_carry_the_pack_display_names(seed):
    host = make_host()
    new = host.new_game(seed)
    assert new.brief.record_kinds
    assert {k.label for k in new.brief.record_kinds} == {
        DISPLAY[k.key] for k in new.brief.record_kinds
    }
    explore_all(host, new.game)
    shown = {name[:1].upper() + name[1:] for name in DISPLAY.values()}
    record_sections = [s.source for s in host.notebook(new.game).sections if ": " in s.source]
    assert record_sections
    assert all(source.split(": ")[0] in shown for source in record_sections)
    for kind in new.brief.record_kinds:
        for suspect in new.brief.suspects:
            result = host.check_records(new.game, suspect.handle, kind.key)
            assert result.label.startswith(kind.label[:1].upper() + kind.label[1:])
            assert set(result.kinds) <= {kind.label}


def test_a_record_key_never_reaches_a_view_when_its_display_name_differs():
    host = make_host()
    new = host.new_game(2)
    explore_all(host, new.game)
    blob = (new.brief.model_dump_json() + host.notebook(new.game).model_dump_json()).lower()
    assert "chapel register" not in blob and "chapel_register" in new.brief.model_dump_json()
