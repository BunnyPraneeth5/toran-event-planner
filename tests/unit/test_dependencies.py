"""pyproject.toml (read by Vercel) and requirements.txt (read by CI and Docker) must agree."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]


def _requirements() -> set[str]:
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def test_runtime_dependencies_match_requirements_txt() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert set(project["dependencies"]) == _requirements()


def test_runtime_dependencies_are_pinned() -> None:
    assert all("==" in requirement for requirement in _requirements())
