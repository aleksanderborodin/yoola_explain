from yoola.config import Settings
from yoola.taxonomy import keyword_hits, load_taxonomy

from conftest import RECIPE_TEXT, SAMPLE_TOS

TAXONOMY = load_taxonomy(Settings(_env_file=None, llm_api_key="x").taxonomy_path)


def test_taxonomy_loads_all_categories():
    ids = {c.id for c in TAXONOMY}
    assert len(TAXONOMY) == 14
    assert {"arbitration", "unilateral_changes", "auto_renewal", "data_sale_sharing"} <= ids
    assert sum(1 for c in TAXONOMY if c.high_stakes) == 4


def test_keyword_prefilter_finds_planted_clauses():
    hits = keyword_hits(SAMPLE_TOS, TAXONOMY)
    for expected in ("arbitration", "unilateral_changes", "liability_limitation",
                     "indemnification", "jurisdiction", "warranty_disclaimer",
                     "content_license"):
        assert expected in hits, f"prefilter missed {expected}"


def test_keyword_prefilter_quiet_on_non_legal_text():
    assert keyword_hits(RECIPE_TEXT, TAXONOMY) == {}
