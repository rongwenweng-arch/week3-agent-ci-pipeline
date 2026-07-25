from src.string_utils import reverse_string, is_palindrome, to_upper


def test_reverse_string():
    assert reverse_string("abc") == "cba"


def test_is_palindrome():
    assert is_palindrome("Never Odd or Even") is True
    assert is_palindrome("hello") is False


def test_to_upper():
    assert to_upper("abc") == "ABC"
