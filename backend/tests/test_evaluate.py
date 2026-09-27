from scripts.evaluate_retrieval import score_ranked


def test_page_level_metrics_require_both_sources_for_multi_document_question():
    candidates = [
        {"source_url": "https://example.edu/old.pdf", "page": 1},
        {"source_url": "https://example.edu/old.pdf", "page": 1},
        {"source_url": "https://example.edu/new.pdf", "page": 2},
    ]
    gold = [
        [{"source_url": "https://example.edu/old.pdf", "page": 1},
         {"source_url": "https://example.edu/old.pdf", "page": 2}],
        [{"source_url": "https://example.edu/new.pdf", "page": 2}],
    ]
    assert score_ranked(candidates, gold) == {
        "first_relevant_rank": 1, "hit_at_5": True, "all_required_at_5": True,
    }
    assert score_ranked(candidates[:2], gold)["all_required_at_5"] is False
    assert score_ranked([{"source_url": "https://example.edu/old.pdf", "page": 2}, candidates[2]], gold)["all_required_at_5"]
