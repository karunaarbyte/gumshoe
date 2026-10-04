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


# --- gumshoe.cases layer rules -----------------------------------------------------------

CASES = SRC / "gumshoe" / "cases"

# layer -> the cases layers it may import
CASES_ALLOWED: dict[str, set[str]] = {
    "core": set(),
    "model": {"core"},
    "rules": {"core", "model"},
    "validate": {"core", "model", "rules"},
    "play": {"core", "model", "rules"},
    "packs": {"core", "model", "rules"},
    "generate": {"core", "model", "rules", "validate", "packs"},
    "simulate": {"core", "model", "rules", "validate", "play"},
    "tools": {"core", "model", "rules", "validate", "play", "packs", "generate", "simulate"},
}
BANNED_MODULES = ("random", "secrets", "time", "datetime", "uuid", "os")
BANNED_CALLS = ("hash", "open")
BANNED_METHODS = ("open", "read_text", "read_bytes", "write_text", "write_bytes")


def cases_layer_problems(root: Path) -> list[str]:
    """Imports between `gumshoe.cases.<layer>` packages that the layer order forbids."""
    cases_root = root / "gumshoe" / "cases"
    problems: list[str] = []
    for path in sources(cases_root):
        parts = path.relative_to(cases_root).parts
        if len(parts) < 2:  # package-level files (public API, __main__) may import any layer
            continue
        layer = parts[0]
        allowed = CASES_ALLOWED.get(layer)
        if allowed is None:
            problems.append(f"{path.relative_to(root)}: unknown layer {layer!r}")
            continue
        for module in sorted(imported_modules(path, root)):
            segments = module.split(".")
            if segments[:2] == ["gumshoe", "cases"] and len(segments) > 2:
                target = segments[2]
                if target != layer and target not in allowed:
                    problems.append(f"{path.relative_to(root)}: {layer} must not import {target}")
    return problems


def cases_decider_problems(root: Path) -> list[str]:
    """Only `cases/play` may import gumshoe.decider."""
    cases_root = root / "gumshoe" / "cases"
    files = [p for p in sources(cases_root) if p.relative_to(cases_root).parts[0] != "play"]
    return violations(files, ("gumshoe.decider",), root)


def cases_determinism_problems(root: Path) -> list[str]:
    """Randomness, clocks, environment and file access are banned outside tools/."""
    cases_root = root / "gumshoe" / "cases"
    problems: list[str] = []
    for path in sources(cases_root):
        parts = path.relative_to(cases_root).parts
        if parts[0] == "tools":
            continue
        rel = path.relative_to(root)
        for module in sorted(imported_modules(path, root)):
            if module.split(".")[0] in BANNED_MODULES:
                problems.append(f"{rel} imports {module}")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in BANNED_CALLS
            ):
                problems.append(f"{rel} calls {node.func.id}()")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in BANNED_METHODS
            ):
                problems.append(f"{rel} calls .{node.func.attr}()")
    return problems


def make_cases_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        target = tmp_path / "gumshoe" / "cases" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return tmp_path


def test_layer_checker_flags_an_upward_import(tmp_path):
    root = make_cases_tree(
        tmp_path,
        {
            "core/a.py": "from gumshoe.cases.model import x\n",
            "validate/b.py": "from gumshoe.cases.play import y\n",
            "model/ok.py": "from gumshoe.cases.core import z\n",
        },
    )
    assert cases_layer_problems(root) == [
        "gumshoe/cases/core/a.py: core must not import model",
        "gumshoe/cases/validate/b.py: validate must not import play",
    ]


def test_layer_checker_flags_unknown_layers_and_allows_package_level_files(tmp_path):
    root = make_cases_tree(
        tmp_path,
        {"mystery/a.py": "x = 1\n", "__init__.py": "from gumshoe.cases.tools import cli\n"},
    )
    assert cases_layer_problems(root) == ["gumshoe/cases/mystery/a.py: unknown layer 'mystery'"]


def test_decider_checker_allows_play_only(tmp_path):
    root = make_cases_tree(
        tmp_path,
        {
            "play/a.py": "from gumshoe.decider import ChoiceQuestion\n",
            "validate/b.py": "from gumshoe.decider import Decider\n",
        },
    )
    assert cases_decider_problems(root) == ["gumshoe/cases/validate/b.py imports gumshoe.decider"]


def test_determinism_checker_bans_clocks_randomness_and_files(tmp_path):
    root = make_cases_tree(
        tmp_path,
        {
            "core/a.py": "import random\nimport time\nfrom datetime import UTC\n",
            "model/b.py": "x = hash('a')\nwith open('f') as fh:\n    pass\n",
            "generate/streams.py": "import random\nimport hashlib\n",
            "tools/cli.py": "import os\n",
            "core/clean.py": "import hashlib\nimport json\n",
        },
    )
    assert cases_determinism_problems(root) == [
        "gumshoe/cases/core/a.py imports datetime",
        "gumshoe/cases/core/a.py imports random",
        "gumshoe/cases/core/a.py imports time",
        "gumshoe/cases/generate/streams.py imports random",
        "gumshoe/cases/model/b.py calls hash()",
        "gumshoe/cases/model/b.py calls open()",
    ]


def test_the_streams_module_has_no_exemption_from_the_determinism_rule():
    streams = CASES / "generate" / "streams.py"
    assert streams.exists()
    assert {m.split(".")[0] for m in imported_modules(streams, SRC)}.isdisjoint(BANNED_MODULES)


def test_decider_checker_exempts_only_the_top_level_play_layer(tmp_path):
    root = make_cases_tree(
        tmp_path,
        {
            "play/a.py": "from gumshoe.decider import Decider\n",
            "play/deep/b.py": "from gumshoe.decider import Decider\n",
            "validate/play/c.py": "from gumshoe.decider import Decider\n",
        },
    )
    assert cases_decider_problems(root) == [
        "gumshoe/cases/validate/play/c.py imports gumshoe.decider"
    ]


def test_determinism_checker_bans_path_file_methods_and_secrets(tmp_path):
    root = make_cases_tree(
        tmp_path,
        {
            "core/a.py": "import secrets\nfrom pathlib import Path\nPath('x').read_text()\n"
            "Path('y').open()\n",
        },
    )
    assert cases_determinism_problems(root) == [
        "gumshoe/cases/core/a.py imports secrets",
        "gumshoe/cases/core/a.py calls .read_text()",
        "gumshoe/cases/core/a.py calls .open()",
    ]


def test_real_cases_layers():
    assert cases_layer_problems(SRC) == []


def test_real_cases_decider_imports():
    assert cases_decider_problems(SRC) == []


def test_real_cases_determinism():
    assert cases_determinism_problems(SRC) == []


def test_code_outside_cases_uses_only_the_cases_public_api():
    outside = [p for p in sources(SRC / "gumshoe") if CASES not in p.parents]
    assert violations(outside, ("gumshoe.cases.",)) == []


# --- the player surface (plan 2b) ---------------------------------------------------------

PLAYER_SURFACE = ("tools/play_cli.py",)
PLAYER_ALLOWED = {"gumshoe.cases.play", "gumshoe.cases.play.session", "gumshoe.cases.play.views"}


def cases_player_surface_problems(root: Path) -> list[str]:
    """Player-facing code sees only the play package's public face; views import no gumshoe code."""
    cases_root = root / "gumshoe" / "cases"
    problems: list[str] = []
    for rel in PLAYER_SURFACE:
        path = cases_root / rel
        if not path.exists():
            continue
        problems += [
            f"{path.relative_to(root)} imports {module}"
            for module in sorted(imported_modules(path, root))
            if module.startswith("gumshoe.cases") and module not in PLAYER_ALLOWED
        ]
    views = cases_root / "play" / "views.py"
    if views.exists():
        problems += [
            f"{views.relative_to(root)} imports {module}"
            for module in sorted(imported_modules(views, root))
            if module.startswith("gumshoe")
        ]
    return problems


def test_player_surface_checker_flags_skeleton_imports(tmp_path):
    root = make_cases_tree(
        tmp_path,
        {
            "tools/play_cli.py": "from gumshoe.cases.model.case import Case\n"
            "from gumshoe.cases.play import GameSession\n"
            "from gumshoe.cases.play.engine import use_source\n",
            "play/views.py": "from gumshoe.cases.model.case import Case\nimport pydantic\n",
        },
    )
    assert cases_player_surface_problems(root) == [
        "gumshoe/cases/tools/play_cli.py imports gumshoe.cases.model.case",
        "gumshoe/cases/tools/play_cli.py imports gumshoe.cases.play.engine",
        "gumshoe/cases/play/views.py imports gumshoe.cases.model.case",
    ]


def test_player_surface_checker_accepts_the_public_face(tmp_path):
    root = make_cases_tree(
        tmp_path,
        {
            "tools/play_cli.py": "from gumshoe.cases.play import GameSession, views\n",
            "play/views.py": "from pydantic import BaseModel\n",
        },
    )
    assert cases_player_surface_problems(root) == []


def test_real_cases_player_surface():
    assert cases_player_surface_problems(SRC) == []


def test_simulate_does_not_import_validate():
    # the simulator is an independent oracle for the validator: it may not borrow its code
    # (spec 6.1 would allow it; declared deviation in plan 2b)
    simulate = sources(CASES / "simulate")
    assert simulate
    assert violations(simulate, ("gumshoe.cases.validate",)) == []


def test_the_generator_replay_is_reachable_from_tools_only():
    """gen_dev may be imported by developer tooling, never by a player surface or the play layer."""
    importers = [
        p.relative_to(CASES)
        for p in sources(CASES)
        if "gumshoe.cases.tools.gen_dev" in imported_modules(p, SRC)
    ]
    assert all(path.parts[0] == "tools" and path.name != "play_cli.py" for path in importers)
    play = sources(CASES / "play")
    assert violations(play, ("gumshoe.cases.generate", "gumshoe.cases.tools"), SRC) == []
    assert "gumshoe.cases.tools.gen_dev" not in PLAYER_ALLOWED
