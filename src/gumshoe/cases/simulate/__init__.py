"""The brute-force player simulator: a test oracle that drives the real play code.

`oracle` knows the truth and plays honestly (reachability, solvability, single points of
failure, fewest source uses); `blind` measures how often reading everything and then guessing
wins. Neither imports `gumshoe.cases.validate`: the agreement tests pit the two against it."""
