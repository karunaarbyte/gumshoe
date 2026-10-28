import shutil
from pathlib import Path

from gumshoe.mcp_server import GameHost
from tests.mcp_server.helpers import SeqIds

FIXTURE = Path(__file__).parents[1] / "fixtures" / "castle_pre_stage5_save.json"


def test_the_pre_stage_5_castle_save_still_loads(tmp_path):
    # Made by the last commit before stage 5; later pack work must keep reading it.
    name = "0123456789abcdef"
    shutil.copy(FIXTURE, tmp_path / f"{name}.json")
    host = GameHost(ids=SeqIds(), saves_dir=tmp_path)
    loaded = host.load_game(name)
    assert len(loaded.brief.suspects) == 5
    assert loaded.brief.status == "playing"
