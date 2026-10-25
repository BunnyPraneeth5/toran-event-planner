"""Architecture rules from CLAUDE.md, checked on every test run."""

import ast
from pathlib import Path

ENGINES = Path(__file__).parents[2] / "app" / "engines"
FORBIDDEN = ("app.ai", "app.api", "app.planner", "app.config")
IO_MODULES = ("os", "pathlib", "socket", "requests", "httpx", "urllib", "json", "time")


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_engines_do_not_import_ai_api_or_planner() -> None:
    for path in ENGINES.glob("*.py"):
        bad = {n for n in _imports(path) if n.startswith(FORBIDDEN)}
        assert not bad, f"{path.name} imports {bad}"


def test_engines_do_not_import_io_modules() -> None:
    for path in ENGINES.glob("*.py"):
        bad = {n for n in _imports(path) if n.split(".")[0] in IO_MODULES}
        assert not bad, f"{path.name} imports {bad}"
