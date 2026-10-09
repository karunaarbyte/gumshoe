import pytest

from gumshoe.cases.packs.loader import load_pack
from tests.packs.fixtures import BASE_TOML, TEST_PRESETS
from tests.packs.mutations import MUTATIONS


def test_the_base_pack_loads_clean():
    result = load_pack(BASE_TOML.encode(), TEST_PRESETS)
    assert result.issues == () and result.pack is not None


@pytest.mark.parametrize("code", sorted(MUTATIONS))
def test_mutation_reports_exactly_its_declared_cascade(code):
    mutation = MUTATIONS[code]
    result = load_pack(mutation.apply(BASE_TOML).encode(), TEST_PRESETS)
    assert {i.code for i in result.issues} == mutation.expected, [
        (i.code, i.path) for i in result.issues
    ]
