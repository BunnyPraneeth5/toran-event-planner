import pytest

from app.web.formatting import format_inr, format_short


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (0, "₹0"),
        (999, "₹999"),
        (1_000, "₹1,000"),
        (80_000, "₹80,000"),
        (2_500_000, "₹25,00,000"),
        (12_345_678, "₹1,23,45,678"),
        (1_000_000_000, "₹1,00,00,00,000"),
        (-40_000, "-₹40,000"),
    ],
)
def test_format_inr_uses_indian_grouping(amount: int, expected: str) -> None:
    assert format_inr(amount) == expected


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (80_000, "₹80,000"),
        (100_000, "₹1 lakh"),
        (2_500_000, "₹25 lakh"),
        (2_550_000, "₹25.5 lakh"),
        (12_500_000, "₹1.25 crore"),
        (1_000_000_000, "₹100 crore"),
    ],
)
def test_format_short_uses_lakh_and_crore(amount: int, expected: str) -> None:
    assert format_short(amount) == expected
