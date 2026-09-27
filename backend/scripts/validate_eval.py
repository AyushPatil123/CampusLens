"""Validate fixed M3 question and page labels without calling a model."""

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from scripts.ingest_corpus import DEFAULT_MANIFEST, load_manifest


DEFAULT_EVAL = Path(__file__).resolve().parents[2] / "eval"
CATEGORIES = {"direct", "paraphrase", "exact", "multi_document", "no_answer"}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate(
    questions: list[dict], labels: list[dict], manifest: list[dict],
    snapshot: dict, db_path: Path | None = None,
) -> dict:
    if not questions or len(questions) != len(labels):
        raise ValueError("Questions and labels must be nonempty and have matching counts")
    question_ids = [record["id"] for record in questions]
    label_ids = [record["id"] for record in labels]
    if len(set(question_ids)) != len(question_ids) or len(set(label_ids)) != len(label_ids):
        raise ValueError("Question and label IDs must be unique")
    if set(question_ids) != set(label_ids):
        raise ValueError("Each question must have exactly one matching label")
    label_by_id = {label["id"]: label for label in labels}
    source_urls = {entry["source_url"] for entry in manifest}
    expected_hashes = {source["source_url"]: source["sha256"] for source in snapshot["sources"]}
    if set(expected_hashes) != source_urls or len(expected_hashes) != len(snapshot["sources"]):
        raise ValueError("Corpus snapshot and manifest sources differ")
    indexed_pages = None
    if db_path is not None:
        with sqlite3.connect(db_path) as db:
            indexed_pages = set(db.execute(
                """SELECT d.source_url, c.page FROM documents d
                   JOIN chunks c ON c.document_id = d.id"""
            ).fetchall())
            actual_hashes = dict(db.execute("SELECT source_url, sha256 FROM documents").fetchall())
            profiles = {row[0] for row in db.execute("SELECT DISTINCT embedding_profile FROM documents")}
            if actual_hashes != expected_hashes or profiles != {snapshot["embedding_profile"]}:
                raise ValueError("Indexed corpus does not match the fixed source hashes and embedding profile")
    categories = Counter()
    for question in questions:
        identifier = question["id"]
        category = question["category"]
        if category not in CATEGORIES or not isinstance(question["question"], str) or not question["question"].strip():
            raise ValueError(f"Invalid question {identifier}")
        categories[category] += 1
        label = label_by_id[identifier]
        groups = label["evidence_groups"]
        if label["answerable"] != bool(groups) or (category == "no_answer") == bool(groups):
            raise ValueError(f"Answerability mismatch for {identifier}")
        if any(not group or len({page["source_url"] for page in group}) != 1 for group in groups):
            raise ValueError(f"Invalid evidence alternatives for {identifier}")
        if category == "multi_document" and len({group[0]["source_url"] for group in groups}) < 2:
            raise ValueError(f"Multi-document question {identifier} needs two sources")
        for group in groups:
            for page in group:
                key = (page["source_url"], page["page"])
                if page["source_url"] not in source_urls or type(page["page"]) is not int or page["page"] < 1:
                    raise ValueError(f"Invalid manifest source or page for {identifier}")
                if indexed_pages is not None and key not in indexed_pages:
                    raise ValueError(f"Gold page not indexed for {identifier}: {key}")
    return dict(categories)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-dir", type=Path, default=DEFAULT_EVAL)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--db", type=Path, help="Also check gold pages against an indexed SQLite database")
    args = parser.parse_args()
    counts = validate(
        read_jsonl(args.eval_dir / "questions.jsonl"),
        read_jsonl(args.eval_dir / "labels.jsonl"),
        load_manifest(args.manifest),
        json.loads((args.eval_dir / "corpus_snapshot.json").read_text(encoding="utf-8")),
        args.db,
    )
    print(json.dumps({"questions": sum(counts.values()), "categories": counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
