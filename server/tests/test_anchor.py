from yoola.anchor import locate_quote

from conftest import SAMPLE_TOS

QUOTE = "Any dispute arising out of or relating to these Terms"


def test_exact_quote_locates_at_correct_offset():
    hit = locate_quote(QUOTE, SAMPLE_TOS, min_score=85)
    assert hit is not None
    offset, score = hit
    assert SAMPLE_TOS[offset : offset + len(QUOTE)] == QUOTE
    assert score >= 99


def test_case_and_whitespace_variation_still_locates():
    assert locate_quote(QUOTE.upper(), SAMPLE_TOS, 85) is not None
    assert locate_quote("any  dispute arising out of or  relating to these terms", SAMPLE_TOS, 85)


def test_light_paraphrase_locates_fuzzily():
    hit = locate_quote("Any dispute arising from or relating to these Terms", SAMPLE_TOS, 85)
    assert hit is not None


def test_fabricated_quote_does_not_locate():
    fabricated = "We promise to never collect any information about you whatsoever at all."
    assert locate_quote(fabricated, SAMPLE_TOS, 85) is None


def test_too_short_quote_rejected():
    assert locate_quote("Terms", SAMPLE_TOS, 85) is None
    assert locate_quote("", SAMPLE_TOS, 85) is None
