from src.calculator import add, subtract, multiply, divide


def test_add():
    assert add(2, 3) == 5  # FAILS while the bug is present (returns -1)


def test_subtract():
    assert subtract(5, 2) == 3


def test_multiply():
    assert multiply(3, 4) == 12


def test_divide():
    assert divide(10, 2) == 5
