"""Enforces the import rules from src/gumshoe/decider/__init__.py by reading the source."""

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src"
DECIDER = SRC / "gumshoe" / "decider"


def imported_modules(path: Path) -> set[str]:
    """Absolute module names imported by a source file (`import x`, `from x import y`)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def sources(folder: Path) -> list[Path]:
    return [p for p in sorted(folder.rglob("*.py")) if "__pycache__" not in p.parts]


def violations(files: list[Path], forbidden_prefixes: tuple[str, ...]) -> list[str]:
    return [
        f"{path.relative_to(SRC)} imports {module}"
        for path in files
        for module in imported_modules(path)
        if module.startswith(forbidden_prefixes)
    ]


def test_contract_is_pure():
    # contract: types and interfaces only. No HTTP, no backends, no tooling.
    forbidden = ("gumshoe.decider.backends", "gumshoe.decider.tools", "httpx")
    files = [p for p in sources(DECIDER / "contract") if p.name != "__init__.py"]
    assert violations(files, forbidden) == []


def test_backends_do_not_depend_on_tools():
    files = [p for p in sources(DECIDER / "backends") if p.name != "__init__.py"]
    assert violations(files, ("gumshoe.decider.tools",)) == []


def test_only_the_entrypoint_imports_tools():
    outside_tools = [
        p
        for p in sources(DECIDER)
        if "tools" not in p.relative_to(DECIDER).parts and p.name != "__main__.py"
    ]
    assert violations(outside_tools, ("gumshoe.decider.tools",)) == []


def test_other_packages_use_only_the_public_decider_api():
    # Anything in gumshoe outside decider/ may import `gumshoe.decider`, never its internals.
    outside = [p for p in sources(SRC / "gumshoe") if DECIDER not in p.parents]
    assert violations(outside, ("gumshoe.decider.",)) == []


def test_public_api_exports_the_essentials():
    import gumshoe.decider as decider

    for name in ("Decider", "make_decider", "DecisionResult", "DeciderError", "ChoiceQuestion"):
        assert hasattr(decider, name), name
    assert set(decider.__all__) >= {"Decider", "make_decider", "DecisionResult"}
