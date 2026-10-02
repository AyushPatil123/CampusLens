"""Compare old/new chunking on cached snapshot PDFs and keyword retrieval; no model calls."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile

from pypdf import PdfReader

from app.documents import chunk_pages, extract_pages
from app.store import Store
from scripts.evaluate_retrieval import score_ranked
from scripts.ingest_corpus import DEFAULT_MANIFEST, load_manifest
from scripts.validate_eval import DEFAULT_EVAL, read_jsonl


def legacy_chunks(pages, size=900, overlap=120):
    """Frozen pre-upgrade word-boundary algorithm for the matched comparison."""
    chunks = []
    for page, raw in pages:
        current, length = [], 0
        for word in raw.split():
            if current and length + len(word) + 1 > size:
                chunks.append((page, " ".join(current)))
                tail, tail_length = [], 0
                for previous in reversed(current):
                    if tail_length + len(previous) + 1 > overlap:
                        break
                    tail.insert(0, previous)
                    tail_length += len(previous) + 1
                current, length = tail, len(" ".join(tail))
            current.append(word)
            length += len(word) + 1
        if current:
            chunks.append((page, " ".join(current)))
    return chunks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/corpus"))
    parser.add_argument("--output", type=Path, default=DEFAULT_EVAL / "extraction_results.json")
    args = parser.parse_args()
    snapshot = json.loads((DEFAULT_EVAL / "corpus_snapshot.json").read_text())
    entries = {entry["source_url"]: entry for entry in load_manifest(DEFAULT_MANIFEST)}
    questions = read_jsonl(DEFAULT_EVAL / "questions.jsonl")
    labels = {item["id"]: item for item in read_jsonl(DEFAULT_EVAL / "labels.jsonl")}
    result = {"evaluated_date": datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat(), "documents": len(snapshot["sources"]),
              "scope": "Matched cached PDF hashes; keyword-only retrieval; no embeddings, OCR, or model calls",
              "chunk_size": 900, "chunk_overlap": 120, "modes": {}}
    with tempfile.TemporaryDirectory(prefix="campuslens-extraction-") as directory:
        stores = {mode: Store(Path(directory) / f"{mode}.sqlite3") for mode in ("legacy", "paragraph")}
        counts = {mode: {"chunks": 0, "pages": 0} for mode in stores}
        warnings = []
        for source in snapshot["sources"]:
            digest = source["sha256"]
            data = (args.cache_dir / f"{digest}.pdf").read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(f"Cached PDF does not match the snapshot: {digest}")
            raw = [(i, page.extract_text() or "") for i, page in enumerate(PdfReader(BytesIO(data)).pages, 1)]
            extraction = extract_pages("source.pdf", data)
            entry = entries[source["source_url"]]
            warnings.extend({"source_url": source["source_url"], "warning": warning} for warning in extraction.warnings)
            for mode, chunks in (("legacy", legacy_chunks(raw)), ("paragraph", chunk_pages(extraction.pages))):
                if {page for page, _ in chunks} != {page for page, text in raw if text.strip()}:
                    raise ValueError(f"Indexed page coverage changed: {digest}")
                if mode == "paragraph" and any(len(text) > 900 for _, text in chunks):
                    raise ValueError("Chunk exceeds the configured size")
                stores[mode].add(f"{digest}.pdf", digest, chunks, [[0.0] for _ in chunks],
                                 title=entry["title"], source_url=source["source_url"], institution=entry["institution"])
                counts[mode]["chunks"] += len(chunks)
                counts[mode]["pages"] += len({page for page, _ in chunks})
        for mode, store in stores.items():
            scored = []
            for question in questions:
                label = labels[question["id"]]
                if not label["answerable"]:
                    continue
                score = score_ranked(store.search(question["question"], [], limit=10, mode="keyword"), label["evidence_groups"])
                scored.append({"id": question["id"], "multi": len(label["evidence_groups"]) > 1, **score})
            multi = [item for item in scored if item["multi"]]
            result["modes"][mode] = {**counts[mode], "answerable_questions": len(scored),
                "hit_at_5_count": sum(item["hit_at_5"] for item in scored),
                "mrr_at_10": round(sum(1 / item["first_relevant_rank"] if item["first_relevant_rank"] else 0 for item in scored) / len(scored), 4),
                "multi_all_required_at_5_count": sum(item["all_required_at_5"] for item in multi),
                "multi_questions": len(multi), "questions": scored}
        result["extraction_warnings"] = warnings
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({mode: {key: value for key, value in summary.items() if key != "questions"}
                      for mode, summary in result["modes"].items()}, indent=2))


if __name__ == "__main__":
    main()
