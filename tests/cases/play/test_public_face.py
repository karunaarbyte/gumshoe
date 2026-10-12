import gumshoe.cases.play as play

EXPECTED = {
    "GameSession", "load_session", "GameOver", "GameNotOver", "StateMismatch", "AccusationPrompt",
    "views", "View", "LocationView", "SuspectView", "RecordKindView", "PlayerCaseView", "FactView",
    "ContradictionView", "SourceResult", "NotebookFact", "NotebookSection", "NotebookView",
    "ParsedAccusation", "Candidate", "AxisOptions", "ResolvedPart", "AxisProblem",
    "AccusationPlan", "AccusationResult", "RevealView", "ReplyViolation", "ReplyCheck",
    "HandleCollision", "PersonaBrief", "UnknownHandle",
}  # fmt: skip


def test_play_exports_exactly_the_player_face_and_no_skeleton_types():
    assert set(play.__all__) == EXPECTED
    for name in EXPECTED:
        assert hasattr(play, name)
    for skeleton in ("Case", "PlayState", "Fact", "Triple", "CaseIndex", "Outcome"):
        assert not hasattr(play, skeleton)
