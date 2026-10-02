"""Compare keyword, dense, and hybrid retrieval on the fixed M3 questions."""

import argparse
import hashlib
import json
import math
import time
from datetime import datetime
from pathlib import Path

from app.config import Settings
from app.errors import ServiceError
from app.model_gateway import ModelGateway
from app.store import Store
from scripts.ingest_corpus import DEFAULT_MANIFEST, load_manifest
from scripts.validate_eval import DEFAULT_EVAL, read_jsonl, validate


MODES = ("keyword", "dense", "hybrid", "hybrid_diverse")


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def score_ranked(candidates: list[dict], evidence_groups: list[list[dict]]) -> dict:
    groups = [{(page["source_url"], page["page"]) for page in group} for group in evidence_groups]
    ranked = [(row["source_url"], row["page"]) for row in candidates]
    first_rank = next((rank for rank, page in enumerate(ranked, 1) if any(page in group for group in groups)), None)
    return {
        "first_relevant_rank": first_rank,
        "hit_at_5": any(group.intersection(ranked[:5]) for group in groups),
        "all_required_at_5": all(group.intersection(ranked[:5]) for group in groups),
    }


def question_digest(questions: list[dict]) -> str:
    values = [(item["id"], item["question"]) for item in questions]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()


def query_vectors(
    questions: list[dict], settings: Settings, cache_path: Path,
    batch_size: int, delay_seconds: float, retries: int,
) -> dict[str, list[float]]:
    digest = question_digest(questions)
    cache = {"embedding_profile": settings.embedding_profile, "questions_sha256": digest, "vectors": {}}
    if cache_path.exists():
        old = json.loads(cache_path.read_text(encoding="utf-8"))
        if old.get("embedding_profile") == settings.embedding_profile and old.get("questions_sha256") == digest:
            cache = old
    missing = [item for item in questions if item["id"] not in cache["vectors"]]
    if missing:
        models = ModelGateway(settings)
        for start in range(0, len(missing), batch_size):
            batch = missing[start:start + batch_size]
            for attempt in range(retries + 1):
                try:
                    vectors = models.call("embed_queries", [item["question"] for item in batch])
                    break
                except ServiceError as exc:
                    if exc.status_code != 429 or attempt == retries:
                        raise
                    wait = min(30 * (attempt + 1), 60)
                    print(f"Query embedding rate limited; retrying batch in {wait}s", flush=True)
                    time.sleep(wait)
            if len(vectors) != len(batch):
                raise ValueError("Embedding provider returned the wrong number of query vectors")
            cache["vectors"].update({item["id"]: vector for item, vector in zip(batch, vectors)})
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
            temporary.write_text(json.dumps(cache), encoding="utf-8")
            temporary.replace(cache_path)
            print(f"Cached query embeddings: {len(cache['vectors'])}/{len(questions)}", flush=True)
            if start + batch_size < len(missing) and delay_seconds:
                time.sleep(delay_seconds)
    return cache["vectors"]


def run_evaluation(
    store: Store, questions: list[dict], labels: list[dict], vectors: dict,
    modes: tuple[str, ...] = MODES,
) -> dict:
    gold = {label["id"]: label for label in labels}
    output = {}
    for mode in modes:
        rows = []
        durations = []
        for item in questions:
            started = time.perf_counter()
            candidates = store.search(
                item["question"], vectors.get(item["id"], []), limit=10,
                institution="University of California, Berkeley", mode=mode,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            durations.append(elapsed_ms)
            label = gold[item["id"]]
            score = score_ranked(candidates, label["evidence_groups"]) if label["answerable"] else None
            rows.append({
                "id": item["id"], "category": item["category"], "latency_ms": round(elapsed_ms, 3),
                "score": score,
                "top_10": [{"source_url": row["source_url"], "page": row["page"]} for row in candidates],
            })
        answerable = [row for row in rows if row["score"] is not None]
        multi = [row for row in answerable if row["category"] == "multi_document"]
        reciprocal_ranks = [
            1 / row["score"]["first_relevant_rank"] if row["score"]["first_relevant_rank"] else 0
            for row in answerable
        ]
        output[mode] = {
            "summary": {
                "labeled_questions": len(answerable),
                "hit_at_5": round(sum(row["score"]["hit_at_5"] for row in answerable) / len(answerable), 4),
                "mrr_at_10": round(sum(reciprocal_ranks) / len(answerable), 4),
                "multi_all_required_at_5": round(
                    sum(row["score"]["all_required_at_5"] for row in multi) / len(multi), 4
                ),
                "retrieval_p50_ms": round(percentile(durations, 50), 3),
                "retrieval_p95_ms": round(percentile(durations, 95), 3),
            },
            "questions": rows,
        }
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/campuslens.sqlite3"))
    parser.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL)
    parser.add_argument("--cache", type=Path, default=Path("data/eval_query_embeddings.json"))
    parser.add_argument("--output", type=Path, default=DEFAULT_EVAL / "baseline_results.json")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--embed-delay", type=float, default=4)
    parser.add_argument("--rate-limit-retries", type=int, default=2)
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    args = parser.parse_args()
    if args.batch_size < 1 or args.embed_delay < 0 or args.rate_limit_retries < 0:
        parser.error("Batch size must be positive; delay and retries must be nonnegative")
    if not args.db.exists():
        parser.error(f"Indexed database does not exist: {args.db}")
    manifest = load_manifest(DEFAULT_MANIFEST)
    questions = read_jsonl(args.eval_dir / "questions.jsonl")
    labels = read_jsonl(args.eval_dir / "labels.jsonl")
    snapshot = json.loads((args.eval_dir / "corpus_snapshot.json").read_text(encoding="utf-8"))
    validate(questions, labels, manifest, snapshot, args.db)
    settings = Settings(db_path=args.db)
    if settings.embedding_profile != snapshot["embedding_profile"]:
        parser.error("Selected embedding profile differs from the fixed corpus snapshot")
    vectors = query_vectors(
        questions, settings, args.cache, args.batch_size, args.embed_delay, args.rate_limit_retries,
    )
    results = run_evaluation(Store(args.db), questions, labels, vectors, tuple(args.modes))
    report = {
        "evaluated_at": datetime.now().astimezone().isoformat(),
        "embedding_profile": settings.embedding_profile,
        "question_count": len(questions),
        "corpus_documents": len(snapshot["sources"]),
        "latency_scope": "SQLite retrieval only; query embeddings were precomputed or loaded from cache",
        "modes": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for mode in args.modes:
        print(mode, json.dumps(results[mode]["summary"], sort_keys=True))
    print("Detailed results:", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
