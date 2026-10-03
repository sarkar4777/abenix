"""Card patterns only fire on numbers that pass the Luhn check."""

from engine.moderation_client import _custom_pattern_hit, _redact

CARD = r"\b(?:\d{4}[-\s]?){3}\d{4}\b"


def test_real_card_numbers_still_match_and_are_masked():
    text = "card 4111 1111 1111 1111 on file"
    assert _custom_pattern_hit(text, [CARD]) == [CARD]
    assert _redact(text, [CARD], "[R]") == "card [R] on file"


def test_sixteen_digit_data_that_fails_luhn_is_left_alone():
    text = "case counts 1234567812345678 and order 2026-1003-0001-0043"
    assert _custom_pattern_hit(text, [CARD]) == []
    assert _redact(text, [CARD], "[R]") == text


def test_other_patterns_are_unchanged():
    ssn = r"\b\d{3}-\d{2}-\d{4}\b"
    assert _custom_pattern_hit("SSN 987-12-3456", [ssn]) == [ssn]
    assert _redact("SSN 987-12-3456", [ssn], "[R]") == "SSN [R]"
