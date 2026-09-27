"""Hybrid dense and FTS5 retrieval over indexed document chunks."""

import json
import math
import re
import sqlite3
from typing import Literal


RetrievalMode = Literal["keyword", "dense", "hybrid"]


def cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def search_chunks(
    db: sqlite3.Connection, question: str, query_embedding: list[float], limit: int = 5,
    institution: str | None = None, document_ids: list[str] | None = None,
    mode: RetrievalMode = "hybrid",
) -> list[dict]:
    if mode not in ("keyword", "dense", "hybrid"):
        raise ValueError(f"Unknown retrieval mode: {mode}")
    conditions = []
    parameters: list[str] = []
    if institution is not None:
        conditions.append("d.institution = ?")
        parameters.append(institution)
    if document_ids is not None:
        if not document_ids:
            return []
        conditions.append("d.id IN (" + ",".join("?" for _ in document_ids) + ")")
        parameters.extend(document_ids)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    records: dict[str, dict] = {}
    dense = []
    if mode in ("dense", "hybrid"):
        rows = db.execute(
            """SELECT c.id, c.page, c.text, c.embedding, d.id AS document_id,
                      d.filename, COALESCE(d.title, d.filename) AS title,
                      d.source_url, d.institution, d.published_or_updated_date
               FROM chunks c JOIN documents d ON d.id = c.document_id""" + where,
            parameters,
        ).fetchall()
        records.update({row["id"]: {key: value for key, value in dict(row).items() if key != "embedding"}
                        for row in rows})
        dense = sorted(rows, key=lambda row: cosine(query_embedding, json.loads(row["embedding"])), reverse=True)[:20]
    lexical = []
    terms = list(dict.fromkeys(re.findall(r"\w+", question.lower())))[:20]
    if mode in ("keyword", "hybrid") and terms:
        expression = " OR ".join('"' + term + '"' for term in terms)
        lexical = db.execute(
            """SELECT c.id, c.page, c.text, d.id AS document_id,
                      d.filename, COALESCE(d.title, d.filename) AS title,
                      d.source_url, d.institution, d.published_or_updated_date
               FROM chunks_fts
               JOIN chunks c ON c.id = chunks_fts.chunk_id
               JOIN documents d ON d.id = c.document_id
               WHERE chunks_fts MATCH ?""" +
            (" AND " + " AND ".join(conditions) if conditions else "") +
            " ORDER BY bm25(chunks_fts) LIMIT 20",
            [expression, *parameters],
        ).fetchall()
        records.update({row["id"]: dict(row) for row in lexical})
    scores: dict[str, float] = {}
    for rank, row in enumerate(dense, 1):
        scores[row["id"]] = scores.get(row["id"], 0) + 1 / (60 + rank)
    for rank, row in enumerate(lexical, 1):
        scores[row["id"]] = scores.get(row["id"], 0) + 1 / (60 + rank)
    ids = sorted(scores, key=scores.get, reverse=True)[:limit]
    return [records[chunk_id] for chunk_id in ids]
