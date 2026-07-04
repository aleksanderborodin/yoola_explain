from yoola.identity import canonicalize, doc_version, hamming, simhash64

from conftest import SAMPLE_TOS


def test_canonicalize_collapses_cosmetic_variation():
    assert canonicalize("  Hello\n\tWORLD  ") == "hello world"
    assert canonicalize("Hello world") == canonicalize("hello   WORLD")


def test_doc_version_ignores_cosmetic_changes():
    assert doc_version(SAMPLE_TOS) == doc_version(SAMPLE_TOS.upper().replace("\n", "  \n"))
    assert doc_version(SAMPLE_TOS) != doc_version(SAMPLE_TOS + " New clause.")
    assert doc_version(SAMPLE_TOS).startswith("sha256:")


def test_simhash_close_for_small_edit_far_for_different_doc():
    base = simhash64(SAMPLE_TOS)
    edited = simhash64(SAMPLE_TOS.replace("May 15, 2025", "June 1, 2025"))
    different = simhash64("The quick brown fox jumps over the lazy dog. " * 100)
    assert hamming(base, edited) <= 6
    assert hamming(base, different) > 15


def test_simhash_empty_and_tiny_inputs():
    assert simhash64("") == 0
    assert isinstance(simhash64("two words"), int)
