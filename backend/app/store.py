import json
import math
import re
import sqlite3
from pathlib import Path
from uuid import uuid4


def cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, filename TEXT NOT NULL,
                    sha256 TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    page INTEGER NOT NULL, text TEXT NOT NULL, embedding TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, text);
                """
            )
            # Older databases have the original four-column documents table.
            existing = {row["name"] for row in db.execute("PRAGMA table_info(documents)")}
            for column in ("title", "source_url", "institution", "published_or_updated_date"):
                if column not in existing:
                    db.execute(f"ALTER TABLE documents ADD COLUMN {column} TEXT")
            if "extraction_warnings" not in existing:
                db.execute("ALTER TABLE documents ADD COLUMN extraction_warnings TEXT NOT NULL DEFAULT '[]'")
            if "embedding_profile" not in existing:
                db.execute("ALTER TABLE documents ADD COLUMN embedding_profile TEXT")

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def by_hash(self, sha256: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM documents WHERE sha256 = ?", (sha256,)).fetchone()
            return dict(row) if row else None

    def get(self, document_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
            return dict(row) if row else None

    def embedding_profiles(self) -> set[str | None]:
        with self.connect() as db:
            return {row[0] for row in db.execute("SELECT DISTINCT embedding_profile FROM documents")}

    def add(
        self,
        filename: str,
        sha256: str,
        chunks: list[tuple[int, str]],
        embeddings: list[list[float]],
        title: str | None = None,
        source_url: str | None = None,
        institution: str | None = None,
        published_or_updated_date: str | None = None,
        extraction_warnings: list[str] | None = None,
        embedding_profile: str | None = None,
    ) -> dict:
        if len(chunks) != len(embeddings):
            raise ValueError("Every chunk needs an embedding")
        document_id = str(uuid4())
        with self.connect() as db:
            db.execute(
                """INSERT INTO documents(
                       id, filename, sha256, title, source_url, institution,
                       published_or_updated_date, extraction_warnings, embedding_profile
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (document_id, filename, sha256, title, source_url, institution,
                 published_or_updated_date, json.dumps(extraction_warnings or []), embedding_profile),
            )
            for (page, content), embedding in zip(chunks, embeddings):
                chunk_id = str(uuid4())
                db.execute(
                    "INSERT INTO chunks(id, document_id, page, text, embedding) VALUES (?, ?, ?, ?, ?)",
                    (chunk_id, document_id, page, content, json.dumps(embedding)),
                )
                db.execute("INSERT INTO chunks_fts(chunk_id, text) VALUES (?, ?)", (chunk_id, content))
        return {
            "id": document_id, "filename": filename, "sha256": sha256, "title": title or filename,
            "source_url": source_url, "institution": institution,
            "published_or_updated_date": published_or_updated_date,
            "extraction_warnings": extraction_warnings or [], "chunk_count": len(chunks),
        }

    def replace(
        self,
        document_id: str,
        filename: str,
        sha256: str,
        chunks: list[tuple[int, str]],
        embeddings: list[list[float]],
        title: str | None = None,
        source_url: str | None = None,
        institution: str | None = None,
        published_or_updated_date: str | None = None,
        extraction_warnings: list[str] | None = None,
        embedding_profile: str | None = None,
    ) -> dict:
        if len(chunks) != len(embeddings):
            raise ValueError("Every chunk needs an embedding")
        with self.connect() as db:
            old = db.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
            if old is None:
                raise KeyError(document_id)
            metadata = {
                "title": title if title is not None else old["title"],
                "source_url": source_url if source_url is not None else old["source_url"],
                "institution": institution if institution is not None else old["institution"],
                "published_or_updated_date": (
                    published_or_updated_date if published_or_updated_date is not None
                    else old["published_or_updated_date"]
                ),
            }
            old_chunk_ids = [row[0] for row in db.execute("SELECT id FROM chunks WHERE document_id = ?", (document_id,))]
            for chunk_id in old_chunk_ids:
                db.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk_id,))
            db.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            db.execute(
                """UPDATE documents SET filename = ?, sha256 = ?, title = ?, source_url = ?,
                   institution = ?, published_or_updated_date = ?, extraction_warnings = ?,
                   embedding_profile = ?
                   WHERE id = ?""",
                (filename, sha256, metadata["title"], metadata["source_url"], metadata["institution"],
                 metadata["published_or_updated_date"], json.dumps(extraction_warnings or []),
                 embedding_profile, document_id),
            )
            for (page, content), embedding in zip(chunks, embeddings):
                chunk_id = str(uuid4())
                db.execute(
                    "INSERT INTO chunks(id, document_id, page, text, embedding) VALUES (?, ?, ?, ?, ?)",
                    (chunk_id, document_id, page, content, json.dumps(embedding)),
                )
                db.execute("INSERT INTO chunks_fts(chunk_id, text) VALUES (?, ?)", (chunk_id, content))
        return {
            "id": document_id, "filename": filename, "sha256": sha256,
            "title": metadata["title"] or filename,
            "source_url": metadata["source_url"], "institution": metadata["institution"],
            "published_or_updated_date": metadata["published_or_updated_date"],
            "extraction_warnings": extraction_warnings or [], "chunk_count": len(chunks),
        }

    def list_documents(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT d.id, d.filename, d.sha256, COALESCE(d.title, d.filename) AS title,
                          d.source_url, d.institution, d.published_or_updated_date,
                          d.extraction_warnings, d.created_at, COUNT(c.id) AS chunk_count
                   FROM documents d LEFT JOIN chunks c ON c.document_id = d.id
                   GROUP BY d.id ORDER BY d.created_at DESC, d.filename"""
            ).fetchall()
            return [{**dict(row), "extraction_warnings": json.loads(row["extraction_warnings"])} for row in rows]

    def delete(self, document_id: str) -> bool:
        with self.connect() as db:
            chunk_ids = [row[0] for row in db.execute("SELECT id FROM chunks WHERE document_id = ?", (document_id,))]
            for chunk_id in chunk_ids:
                db.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk_id,))
            cursor = db.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            return cursor.rowcount > 0

    def search(
        self, question: str, query_embedding: list[float], limit: int = 5,
        institution: str | None = None, document_ids: list[str] | None = None,
    ) -> list[dict]:
        with self.connect() as db:
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
            rows = db.execute(
                """SELECT c.id, c.page, c.text, c.embedding, d.id AS document_id,
                          d.filename, COALESCE(d.title, d.filename) AS title,
                          d.source_url, d.institution, d.published_or_updated_date
                   FROM chunks c JOIN documents d ON d.id = c.document_id""" + where,
                parameters,
            ).fetchall()
            if not rows:
                return []
            records = {row["id"]: dict(row) for row in rows}
            dense = sorted(rows, key=lambda row: cosine(query_embedding, json.loads(row["embedding"])), reverse=True)[:20]
            terms = list(dict.fromkeys(re.findall(r"\w+", question.lower())))[:20]
            lexical = []
            if terms:
                expression = " OR ".join('"' + term + '"' for term in terms)
                lexical = db.execute(
                    """SELECT chunks_fts.chunk_id FROM chunks_fts
                       JOIN chunks c ON c.id = chunks_fts.chunk_id
                       JOIN documents d ON d.id = c.document_id
                       WHERE chunks_fts MATCH ?""" +
                    (" AND " + " AND ".join(conditions) if conditions else "") +
                    " ORDER BY bm25(chunks_fts) LIMIT 20",
                    [expression, *parameters],
                ).fetchall()
            scores: dict[str, float] = {}
            for rank, row in enumerate(dense, 1):
                scores[row["id"]] = scores.get(row["id"], 0) + 1 / (60 + rank)
            for rank, row in enumerate(lexical, 1):
                scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0) + 1 / (60 + rank)
            ids = sorted(scores, key=scores.get, reverse=True)[:limit]
            return [
                {key: value for key, value in records[chunk_id].items() if key != "embedding"}
                for chunk_id in ids
            ]
