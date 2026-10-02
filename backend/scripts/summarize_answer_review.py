"""Count manually reviewed M4 answers without hiding incomplete samples."""

import argparse
import json
from pathlib import Path

from scripts.validate_eval import DEFAULT_EVAL, read_jsonl


def summarize(questions: list[dict], sample: dict, responses: list[dict], reviews: list[dict]) -> dict:
    ids = sample["question_ids"]
    by_id = {item["id"]: item for item in questions}
    if len(ids) != len(set(ids)) or set(ids) - set(by_id):
        raise ValueError("Invalid fixed answer sample")
    response_ids = [item["id"] for item in responses]
    review_ids = [item["id"] for item in reviews]
    if len(response_ids) != len(set(response_ids)) or len(review_ids) != len(set(review_ids)):
        raise ValueError("Duplicate answer response or review ID")
    if set(review_ids) - set(response_ids) or set(response_ids) - set(ids):
        raise ValueError("Review without response or response outside sample")
    answerable = [row for row in reviews if by_id[row["id"]]["category"] != "no_answer"]
    no_answer = [row for row in reviews if by_id[row["id"]]["category"] == "no_answer"]
    for row in answerable:
        if any(type(row[key]) is not bool for key in ("supported", "complete", "citation_correct")):
            raise ValueError(f"Incomplete answerable rubric for {row['id']}")
    for row in no_answer:
        if type(row["refusal_correct"]) is not bool:
            raise ValueError(f"Incomplete refusal rubric for {row['id']}")
    return {
        "sample_size": len(ids), "responses_saved": len(responses), "reviewed": len(reviews),
        "complete_sample": set(review_ids) == set(ids),
        "answerable_reviewed": len(answerable),
        "supported": sum(row["supported"] for row in answerable),
        "complete": sum(row["complete"] for row in answerable),
        "citation_correct": sum(row["citation_correct"] for row in answerable),
        "no_answer_reviewed": len(no_answer),
        "refusal_correct": sum(row["refusal_correct"] for row in no_answer),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL)
    parser.add_argument("--responses", type=Path, default=Path("data/answer_baseline.jsonl"))
    parser.add_argument("--reviews", type=Path, default=DEFAULT_EVAL / "answer_review.jsonl")
    args = parser.parse_args()
    result = summarize(
        read_jsonl(args.eval_dir / "questions.jsonl"),
        json.loads((args.eval_dir / "answer_sample.json").read_text(encoding="utf-8")),
        read_jsonl(args.responses) if args.responses.exists() else [],
        read_jsonl(args.reviews),
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
