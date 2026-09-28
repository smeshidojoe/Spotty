import pytest

from spotty.search import calc


@pytest.mark.parametrize("text, answer", [
    ("12*(3+4)^2", "588"),
    ("2+2", "4"),
    ("1,5+1", "2.5"),
    ("3 × 4", "12"),
    ("sqrt(16)", "4"),
    ("10/3", "3.33333333333"),
    ("100/7*7", "100"),
    ("pi*2", "6.28318530718"),
])
def test_answers(text, answer):
    assert calc.evaluate(text) == answer


@pytest.mark.parametrize("text", ["2024", "abc", "1/0", "", "import os", "__class__"])
def test_not_an_expression(text):
    # Одно число — поиск «2024», а не вычисление; деление на ноль — не ответ.
    assert calc.evaluate(text) is None
