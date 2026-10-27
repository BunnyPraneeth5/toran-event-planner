"""The Indian theme: AA contrast for every token pair, hand-made SVGs within budget, no
inline styles anywhere."""

import json
import re
from pathlib import Path

import pytest

from app.web.links import ICON_KEYS, category_icon

ROOT = Path(__file__).parents[2] / "app"
CSS = (ROOT / "web" / "static" / "css" / "app.css").read_text(encoding="utf-8")
IMG = ROOT / "web" / "static" / "img"
TEMPLATES = ROOT / "web" / "templates"
SVG_BUDGET_BYTES = 30_000

# (foreground, background, minimum ratio). Marigold and turmeric are decoration only.
PAIRS = [
    ("text", "bg", 4.5),
    ("text", "surface", 4.5),
    ("muted", "bg", 4.5),
    ("muted", "surface", 4.5),
    ("accent", "bg", 4.5),
    ("accent", "surface", 4.5),
    ("accent-text", "accent", 4.5),
    ("needed", "bg", 4.5),
    ("needed", "surface", 4.5),
    ("mehendi", "surface", 4.5),
    ("peacock", "surface", 4.5),
    ("text", "warn-bg", 4.5),
    ("warn-border", "warn-bg", 3.0),
    ("focus", "bg", 3.0),
    ("focus", "surface", 3.0),
]


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-f]{6});", block))


def _palettes() -> dict[str, dict[str, str]]:
    light = _tokens(re.search(r"^:root \{(.*?)^\}", CSS, re.S | re.M).group(1))  # type: ignore[union-attr]
    dark_block = re.search(  # type: ignore[union-attr]
        r"@media \(prefers-color-scheme: dark\) \{\s*:root \{(.*?)\}", CSS, re.S
    ).group(1)
    return {"light": light, "dark": {**light, **_tokens(dark_block)}}


def _luminance(colour: str) -> float:
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    high, low = sorted([_luminance(a), _luminance(b)], reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_palette_has_the_occasion_colours_in_both_modes() -> None:
    for mode, palette in _palettes().items():
        for token in ("accent", "marigold", "turmeric", "mehendi", "peacock"):
            assert token in palette, (mode, token)
    assert len(_tokens(CSS.split("@media (prefers-color-scheme: dark)")[1])) >= 15


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize(("fg", "bg", "minimum"), PAIRS)
def test_every_token_pair_meets_wcag_aa(mode: str, fg: str, bg: str, minimum: float) -> None:
    palette = _palettes()[mode]

    assert _contrast(palette[fg], palette[bg]) >= minimum, (mode, fg, bg)


def test_contrast_maths_matches_known_values() -> None:
    assert _contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert _contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


def test_svgs_exist_and_stay_within_budget() -> None:
    names = {p.name for p in IMG.glob("*.svg")}

    expected = {"toran.svg", "favicon.svg", "rangoli-corner.svg", "paisley-divider.svg"}
    expected.add("icons.svg")
    assert expected <= names
    assert sum(p.stat().st_size for p in IMG.glob("*.svg")) < SVG_BUDGET_BYTES


@pytest.mark.parametrize("path", sorted(IMG.glob("*.svg")), ids=lambda p: p.name)
def test_svgs_are_plain_drawings(path: Path) -> None:
    svg = path.read_text(encoding="utf-8")

    assert svg.lstrip().startswith("<svg")
    assert "Drawn for Toran" in svg or "drawn for Toran" in svg
    for forbidden in ("style=", "<style", "<script", "http://", "https://", "<image", "xlink:href"):
        if forbidden == "http://":
            svg_body = svg.replace('xmlns="http://www.w3.org/2000/svg"', "")
            assert forbidden not in svg_body, path.name
        else:
            assert forbidden not in svg, (path.name, forbidden)


def test_every_category_has_an_icon() -> None:
    sprite = (IMG / "icons.svg").read_text(encoding="utf-8")
    categories = json.loads((ROOT / "data" / "categories.json").read_text(encoding="utf-8"))
    keys = {c["key"] for c in categories["categories"]}

    assert keys <= ICON_KEYS
    for key in ICON_KEYS:
        assert f'<symbol id="cat-{key}" viewBox="0 0 24 24">' in sprite
    assert category_icon("venue") == "/static/img/icons.svg#cat-venue"
    assert category_icon("fireworks") == "/static/img/icons.svg#cat-other"


@pytest.mark.parametrize("path", sorted(TEMPLATES.rglob("*.html")), ids=lambda p: p.name)
def test_templates_have_no_inline_styles(path: Path) -> None:
    html = path.read_text(encoding="utf-8")

    assert "style=" not in html
    assert "<style" not in html


def test_decorations_are_hidden_from_screen_readers() -> None:
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    budget = (TEMPLATES / "partials" / "budget.html").read_text(encoding="utf-8")

    assert '<div class="toran" aria-hidden="true"></div>' in base
    assert '<link rel="icon" href="/static/img/favicon.svg" type="image/svg+xml">' in base
    assert '<svg class="icon" aria-hidden="true" focusable="false">' in budget


def test_heading_font_is_devanagari_capable_with_swap() -> None:
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    assert "family=Rozha+One" in base
    assert "display=swap" in base
    assert "family=Noto+Sans" in base
    assert '--heading-font: "Rozha One"' in CSS


def test_nothing_moves_except_smooth_scroll_when_motion_is_allowed() -> None:
    assert "@keyframes" not in CSS
    for value in re.findall(r"(?:animation|transition)[\w-]*:\s*([^;]+);", CSS):
        assert value.startswith("none"), value
