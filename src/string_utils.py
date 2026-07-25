"""Small string-utility module. Unrelated to calculator.py on purpose,
so the test-impact-analysis stage has something safe to skip."""


def reverse_string(s):
    return s[::-1]  # tweak


def is_palindrome(s):
    cleaned = s.lower().replace(" ", "")
    return cleaned == cleaned[::-1]


def to_upper(s):
    return s.upper()
