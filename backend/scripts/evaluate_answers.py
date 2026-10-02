"""Run the fixed M4 answer sample through the production answer service."""

import argparse
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from app.config import Settings
from app.errors import ServiceError
from app.model_gateway import ModelGateway
from app.services import DocumentService
from app.store import Store
from scripts.evaluate_retrieval import query_vectors
from scripts.ingest_corpus import DEFAULT_MANIFEST, load_manifest
from scripts.validate_eval import DEFAULT_EVAL, read_jsonl, validate


class CachedQueryGateway(ModelGateway):
    """Use the fixed M3 query vectors while preserving the production answer path."""

    def __init__(self, settings: Settings, vectors_by_question: dict[str, list[float]]):
        super().__init__(settings)
        self.vectors_by_question = vectors_by_question

    def call(self, method: str, *args):
        if method == "embed_query":
            return self.vectors_by_question[args[0]]
        return super().call(method, *args)


def selected_questions(questions: list[dict], sample: dict) -> list[dict]:
    ids = sample["question_ids"]
    by_id = {item["id"]: item for item in questions}
    if len(ids) != len(set(ids)) or set(ids) - set(by_id):
        raise ValueError("Answer sample has duplicate or unknown question IDs")
    counts = Counter(by_id[identifier]["category"] for identifier in ids)
    expected = {"direct": 5, "paraphrase": 5, "exact": 5, "multi_document": 5, "no_answer": 10}
    if counts != expected:
        raise ValueError(f"Answer sample category counts differ from {expected}: {dict(counts)}")
    return [by_id[identifier] for identifier in ids]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/campuslens.sqlite3"))
    parser.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL)
    parser.add_argument("--cache", type=Path, default=Path("data/eval_query_embeddings.json"))
    parser.add_argument("--output", type=Path, default=Path("data/answer_baseline.jsonl"))
    parser.add_argument("--retrieval-mode", choices=("hybrid", "hybrid_diverse"), default="hybrid")
    parser.add_argument("--delay", type=float, default=4)
    parser.add_argument("--rate-limit-retries", type=int, default=2)
    args = parser.parse_args()
    if args.delay < 0 or args.rate_limit_retries < 0:
        parser.error("Delay and retries must be nonnegative")
    if not args.db.exists():
        parser.error(f"Indexed database does not exist: {args.db}")
    questions = read_jsonl(args.eval_dir / "questions.jsonl")
    labels = read_jsonl(args.eval_dir / "labels.jsonl")
    snapshot = json.loads((args.eval_dir / "corpus_snapshot.json").read_text(encoding="utf-8"))
    validate(questions, labels, load_manifest(DEFAULT_MANIFEST), snapshot, args.db)
    sample = json.loads((args.eval_dir / "answer_sample.json").read_text(encoding="utf-8"))
    selected = selected_questions(questions, sample)
    settings = Settings(db_path=args.db)
    if settings.embedding_profile != snapshot["embedding_profile"]:
        parser.error("Selected embedding profile differs from the fixed corpus snapshot")
    vectors = query_vectors(questions, settings, args.cache, 16, 4, args.rate_limit_retries)
    gateway = CachedQueryGateway(settings, {item["question"]: vectors[item["id"]] for item in selected})
    service = DocumentService(settings, Store(args.db), gateway)
    existing = {}
    if args.output.exists():
        for row in read_jsonl(args.output):
            existing[row["id"]] = row
        if set(existing) - {item["id"] for item in selected}:
            parser.error("Output contains IDs outside the fixed answer sample")
        expected_model = settings.gemini_answer_model if settings.model_provider == "gemini" else settings.answer_model
        by_id = {item["id"]: item for item in selected}
        if any(row["question"] != by_id[identifier]["question"] or
               row["embedding_profile"] != settings.embedding_profile or
               row["answer_model"] != expected_model or
               row.get("retrieval_mode", "hybrid") != args.retrieval_mode for identifier, row in existing.items()):
            parser.error("Existing output uses different questions or model settings; choose a new output file")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    failed = []
    for item in selected:
        if item["id"] in existing:
            continue
        try:
            for attempt in range(args.rate_limit_retries + 1):
                try:
                    started = time.perf_counter()
                    response = service.ask(
                        item["question"], institution="University of California, Berkeley",
                        retrieval_mode=args.retrieval_mode,
                    )
                    duration_ms = round((time.perf_counter() - started) * 1000, 3)
                    break
                except ServiceError as exc:
                    if exc.status_code not in (429, 502) or attempt == args.rate_limit_retries:
                        raise
                    wait = min(30 * (attempt + 1), 60)
                    print(f"Transient model error on {item['id']}; retrying in {wait}s", flush=True)
                    time.sleep(wait)
        except ServiceError as exc:
            if exc.status_code == 429:
                print(f"Model rate limit stopped the run at {item['id']}; {len(existing)} responses are saved. Rerun later.")
                return 2
            failed.append(item["id"])
            print(f"Could not save {item['id']}: {exc.status_code} {exc.detail}", flush=True)
            continue
        row = {
            "id": item["id"], "category": item["category"], "question": item["question"],
            "answer": response["answer"], "citations": response["citations"],
            "answer_model": settings.gemini_answer_model if settings.model_provider == "gemini" else settings.answer_model,
            "embedding_profile": settings.embedding_profile,
            "retrieval_mode": args.retrieval_mode,
            "evaluated_at": datetime.now().astimezone().isoformat(),
            "service_latency_ms": duration_ms,
        }
        with args.output.open("a", encoding="utf-8") as output:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"Saved {item['id']} ({len(existing) + 1}/{len(selected)})", flush=True)
        existing[item["id"]] = row
        if len(existing) < len(selected) and args.delay:
            time.sleep(args.delay)
    print(f"Saved {len(existing)} answer responses to {args.output}")
    if failed:
        print(f"Retry remaining IDs by rerunning this command: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
