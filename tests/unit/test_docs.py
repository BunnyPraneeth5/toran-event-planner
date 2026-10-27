"""The docs stay honest: every linked file, every named test and every named function in
README.md, docs/PROBLEM_ALIGNMENT.md and docs/SECURITY.md exists."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
DOCS = [ROOT / "README.md", ROOT / "docs" / "PROBLEM_ALIGNMENT.md", ROOT / "docs" / "SECURITY.md"]
TEST_SOURCES = "\n".join(
    p.read_text(encoding="utf-8") for d in ("tests", "e2e") for p in (ROOT / d).rglob("*.py")
)


def _links(doc: Path) -> list[str]:
    targets = re.findall(r"\]\(([^)#]+)\)", doc.read_text(encoding="utf-8"))
    return [t for t in targets if not t.startswith("http")]


@pytest.mark.parametrize("doc", DOCS, ids=lambda d: d.name)
def test_every_linked_file_exists(doc: Path) -> None:
    for target in _links(doc):
        assert (doc.parent / target).exists(), f"{doc.name} links to missing {target}"


@pytest.mark.parametrize("doc", DOCS, ids=lambda d: d.name)
def test_every_named_test_exists(doc: Path) -> None:
    names = set(re.findall(r"`(test_\w+)`", doc.read_text(encoding="utf-8")))

    for name in names:
        assert f"def {name}(" in TEST_SOURCES, f"{doc.name} names missing test {name}"


@pytest.mark.parametrize("doc", DOCS, ids=lambda d: d.name)
def test_every_named_function_exists_in_its_linked_file(doc: Path) -> None:
    """A row or bullet that links app code and names `something` must define it there."""
    code_link = re.compile(r"\]\((\.{0,2}/?[^)]*app/[^)]+\.py)\)((?: `\w+`,?)+)")
    for line in doc.read_text(encoding="utf-8").splitlines():
        for target, names in code_link.findall(line):
            source = (doc.parent / target).read_text(encoding="utf-8")
            for name in re.findall(r"`(\w+)`", names):
                pattern = rf"^(?:async )?(?:def|class) {name}\b|^{name}\b"
                assert re.search(pattern, source, re.M), f"{doc.name}: {name} not in {target}"
