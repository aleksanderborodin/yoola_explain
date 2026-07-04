from yoola.plausibility import check_plausibility

from conftest import RECIPE_TEXT, SAMPLE_TOS


def test_sample_tos_passes():
    result = check_plausibility(SAMPLE_TOS, min_words=120, min_density=2.0)
    assert result.ok
    assert result.density > 5


def test_recipe_fails():
    assert not check_plausibility(RECIPE_TEXT, min_words=120, min_density=2.0).ok


def test_short_text_fails_even_if_legal():
    assert not check_plausibility("terms of service liability warranty", 120, 2.0).ok
