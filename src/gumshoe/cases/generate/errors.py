"""Errors of the generator."""


class GenerationError(Exception):
    """A stage cannot produce an output. On a pack that passes the pack checks this is a bug."""
