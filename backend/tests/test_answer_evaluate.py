import json

import pytest

from scripts.evaluate_answers import selected_questions
from scripts.summarize_answer_review import summarize
from scripts.validate_eval import DEFAULT_EVAL, read_jsonl


def test_fixed_answer_sample_includes_all_no_answer_cases():
    questions = read_jsonl(DEFAULT_EVAL / "questions.jsonl")
    sample = json.loads((DEFAULT_EVAL / "answer_sample.json").read_text(encoding="utf-8"))
    selected = selected_questions(questions, sample)
    assert len(selected) == 30
    assert {item["id"] for item in selected if item["category"] == "no_answer"} == {
        f"Q{number:03}" for number in range(51, 61)
    }


def test_review_summary_keeps_partial_counts_separate_from_refusals():
    questions = [{"id": "A", "category": "direct"}, {"id": "N", "category": "no_answer"}]
    sample = {"question_ids": ["A", "N"]}
    responses = [{"id": "A"}, {"id": "N"}]
    reviews = [{"id": "A", "supported": True, "complete": True, "citation_correct": False}]
    partial = summarize(questions, sample, responses, reviews)
    assert partial["complete_sample"] is False
    assert partial["citation_correct"] == 0
    assert partial["no_answer_reviewed"] == 0
    complete = summarize(questions, sample, responses, reviews + [{"id": "N", "refusal_correct": True}])
    assert complete["complete_sample"] is True
    assert complete["refusal_correct"] == 1
    with pytest.raises(ValueError, match="Review without response"):
        summarize(questions, sample, [{"id": "A"}], reviews + [{"id": "N", "refusal_correct": True}])
