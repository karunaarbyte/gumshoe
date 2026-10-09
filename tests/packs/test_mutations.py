import pytest

from gumshoe.cases.packs.loader import load_pack
from tests.packs.fixtures import BASE_TOML, TEST_PRESETS
from tests.packs.mutations import MUTATIONS, STAGE_8_CODES


def test_the_base_pack_loads_clean():
    result = load_pack(BASE_TOML.encode(), TEST_PRESETS)
    assert result.issues == () and result.pack is not None


# stage 8 is not in the load pipeline yet: test_skin_inputs.py runs its mutations
@pytest.mark.parametrize("code", sorted(set(MUTATIONS) - STAGE_8_CODES))
def test_mutation_reports_exactly_its_declared_cascade(code):
    mutation = MUTATIONS[code]
    result = load_pack(mutation.apply(BASE_TOML).encode(), TEST_PRESETS)
    assert {i.code for i in result.issues} == mutation.expected, [
        (i.code, i.path) for i in result.issues
    ]
