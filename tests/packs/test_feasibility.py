from gumshoe.cases.packs.check.feasibility import reachable_location_records
from gumshoe.cases.packs.loader import load_pack
from tests.packs.fixtures import BASE_TOML, TEST_PRESETS


def test_reachable_location_records_for_the_base_pack():
    pack = load_pack(BASE_TOML.encode(), TEST_PRESETS).pack
    # one suspect kind (ledger) and one place kind (gate_log); two record kinds are drawn,
    # so exactly one of them is about a place
    assert list(reachable_location_records(pack, 2)) == [1]
