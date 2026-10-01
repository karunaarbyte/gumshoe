"""Enforces the import rules from src/gumshoe/decider/__init__.py by reading the source."""

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src"
DECIDER = SRC / "gumshoe" / "decider"


def is_module(name: str, root: Path) -> bool:
    """Is `name` (dotted) a real module or package under root, as opposed to a plain name?"""
    base = root / name.replace(".", "/")
    return base.with_suffix(".py").exists() or base.is_dir()


def imported_modules(path: Path, root: Path = SRC) -> set[str]:
    """Absolute names of the modules a source file imports.

    Handles `import a.b`, `from a.b import c` (counting `a.b.c` when it is itself a module, so
    `from gumshoe.decider import tools` is seen) and relative imports like `from ..tools import x`.
    """
    package = list(path.relative_to(root).parts[:-1])  # the package this file lives in
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                parts = base + (node.module.split(".") if node.module else [])
            else:
                parts = node.module.split(".") if node.module else []
            if not parts:
                continue
            module = ".".join(parts)
            found.add(module)
            found.update(
                f"{module}.{alias.name}"
                for alias in node.names
                if is_module(f"{module}.{alias.name}", root)
            )
    return found


def sources(folder: Path) -> list[Path]:
    return [p for p in sorted(folder.rglob("*.py")) if "__pycache__" not in p.parts]


def violations(
    files: list[Path], forbidden_prefixes: tuple[str, ...], root: Path = SRC
) -> list[str]:
    return [
        f"{path.relative_to(root)} imports {module}"
        for path in files
        for module in sorted(imported_modules(path, root))
        if module.startswith(forbidden_prefixes)
    ]


# --- the rules ---------------------------------------------------------------------------


def test_contract_is_pure():
    # contract: types and interfaces only. No HTTP, no backends, no tooling.
    forbidden = (
        "gumshoe.decider.shadow",
        "gumshoe.decider.backends",
        "gumshoe.decider.tools",
        "httpx",
    )
    files = [p for p in sources(DECIDER / "contract") if p.name != "__init__.py"]
    assert violations(files, forbidden) == []


def test_shadow_depends_only_on_contract():
    forbidden = ("gumshoe.decider.backends", "gumshoe.decider.tools", "httpx")
    files = [p for p in sources(DECIDER / "shadow") if p.name != "__init__.py"]
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


def test_decider_never_imports_stats_or_api():
    assert violations(sources(DECIDER), ("gumshoe.stats", "gumshoe.api")) == []


def test_stats_never_imports_api():
    assert violations(sources(SRC / "gumshoe" / "stats"), ("gumshoe.api",)) == []


def test_other_packages_use_only_the_public_decider_api():
    # Anything in gumshoe outside decider/ may import `gumshoe.decider`, never its submodules.
    outside = [p for p in sources(SRC / "gumshoe") if DECIDER not in p.parents]
    assert violations(outside, ("gumshoe.decider.",)) == []


def test_public_api_exports_the_essentials():
    import gumshoe.decider as decider

    for name in ("Decider", "make_decider", "DecisionResult", "DeciderError", "ChoiceQuestion"):
        assert hasattr(decider, name), name
    assert set(decider.__all__) >= {"Decider", "make_decider", "DecisionResult"}


# --- the checker itself: it must catch what it claims to catch ---------------------------


def make_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    """Build a fake src/ with gumshoe/decider/{contract,backends,tools} and the given sources."""
    for rel in ("gumshoe/decider/contract", "gumshoe/decider/backends", "gumshoe/decider/tools"):
        (tmp_path / rel).mkdir(parents=True)
        (tmp_path / rel / "__init__.py").write_text("")
    (tmp_path / "gumshoe" / "__init__.py").write_text("")
    (tmp_path / "gumshoe" / "decider" / "__init__.py").write_text("def make_decider(): ...\n")
    for rel, text in files.items():
        (tmp_path / rel).write_text(text)
    return tmp_path


def test_checker_sees_absolute_submodule_imports(tmp_path):
    root = make_tree(
        tmp_path, {"gumshoe/decider/contract/x.py": "import gumshoe.decider.tools.cli\n"}
    )
    assert imported_modules(root / "gumshoe/decider/contract/x.py", root) >= {
        "gumshoe.decider.tools.cli"
    }


def test_checker_sees_from_package_import_submodule(tmp_path):
    root = make_tree(
        tmp_path, {"gumshoe/decider/contract/x.py": "from gumshoe.decider import tools\n"}
    )
    path = root / "gumshoe/decider/contract/x.py"
    assert violations([path], ("gumshoe.decider.tools",), root) == [
        "gumshoe/decider/contract/x.py imports gumshoe.decider.tools"
    ]


def test_checker_resolves_relative_imports(tmp_path):
    root = make_tree(
        tmp_path,
        {
            "gumshoe/decider/contract/a.py": "from ..tools import cli\n",
            "gumshoe/decider/contract/b.py": "from ..backends.client import SystemOneClient\n",
            "gumshoe/decider/contract/c.py": "from . import models\n",
        },
    )
    a, b, c = (root / f"gumshoe/decider/contract/{n}.py" for n in "abc")
    assert "gumshoe.decider.tools" in imported_modules(a, root)
    assert "gumshoe.decider.backends.client" in imported_modules(b, root)
    assert "gumshoe.decider.contract" in imported_modules(c, root)


def test_checker_does_not_flag_plain_names_from_the_public_api(tmp_path):
    root = make_tree(
        tmp_path, {"gumshoe/other.py": "from gumshoe.decider import make_decider, Decider\n"}
    )
    path = root / "gumshoe/other.py"
    assert imported_modules(path, root) == {
        "gumshoe.decider"
    }  # make_decider is a name, not a module
    assert violations([path], ("gumshoe.decider.",), root) == []
