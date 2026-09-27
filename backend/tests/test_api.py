from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers import format_sources
from app.store import Store


class FakeProvider:
    def embed_documents(self, texts):
        return [[float("tuition" in text.lower()), float("library" in text.lower())] for text in texts]

    def embed_query(self, text):
        return self.embed_documents([text])[0]

    def answer(self, question, sources):
        return "Tuition is due on August 15 [1]."


def test_upload_ask_and_delete(tmp_path: Path):
    client = TestClient(create_app(Settings(db_path=tmp_path / "test.sqlite3"), FakeProvider()))
    assert client.get("/health").json() == {"status": "ok"}
    upload = client.post("/documents", files={"file": ("policy.txt", b"Tuition is due on August 15.")})
    assert upload.status_code == 201
    document_id = upload.json()["id"]
    assert client.post("/documents", files={"file": ("policy.txt", b"Tuition is due on August 15.")}).status_code == 409
    response = client.post("/ask", json={"question": "When is tuition due?"})
    assert response.status_code == 200
    assert response.json()["citations"][0]["document_id"] == document_id
    assert response.json()["citations"][0]["page"] == 1
    assert client.delete(f"/documents/{document_id}").status_code == 204
    assert client.get("/documents").json() == []
    assert client.post("/ask", json={"question": "When is tuition due?"}).json()["citations"] == []


def test_rejects_empty_and_wrong_format(tmp_path: Path):
    client = TestClient(create_app(Settings(db_path=tmp_path / "test.sqlite3"), FakeProvider()))
    assert client.post("/documents", files={"file": ("image.png", b"abc")}).status_code == 415
    assert client.post("/documents", files={"file": ("empty.txt", b"  ")}).status_code == 422


def test_keyword_signal_finds_exact_policy_code(tmp_path: Path):
    store = Store(tmp_path / "search.sqlite3")
    store.add("general.txt", "hash-one", [(1, "The campus has a student library.")], [[1.0, 0.0]])
    target = store.add("policy.txt", "hash-two", [(3, "Policy AB123 sets the appeal deadline.")], [[0.0, 1.0]])
    results = store.search("AB123", [1.0, 0.0])
    assert results[0]["document_id"] == target["id"]
    assert results[0]["page"] == 3
    assert store.delete(target["id"])
    assert all(result["document_id"] != target["id"] for result in store.search("AB123", [1.0, 0.0]))


def test_search_filters_restrict_dense_and_keyword_candidates(tmp_path: Path):
    store = Store(tmp_path / "filters.sqlite3")
    first = store.add("one.txt", "first", [(1, "Policy AB123 applies here.")], [[1.0]], institution="Berkeley")
    other = store.add("two.txt", "second", [(2, "Policy AB123 applies elsewhere.")], [[1.0]], institution="Other")
    assert [row["document_id"] for row in store.search("AB123", [1.0], institution="Berkeley")] == [first["id"]]
    assert [row["document_id"] for row in store.search("AB123", [1.0], document_ids=[other["id"]])] == [other["id"]]
    assert store.search("AB123", [1.0], document_ids=[]) == []
    assert store.search("AB123", [1.0], institution="Berkeley", document_ids=[other["id"]]) == []


def test_ask_filters_citations_by_institution_and_document(tmp_path: Path):
    client = TestClient(create_app(Settings(db_path=tmp_path / "ask-filters.sqlite3"), FakeProvider()))
    first = client.post("/documents", data={"institution": "Berkeley"},
                        files={"file": ("one.txt", b"Tuition is due on August 15.")}).json()
    second = client.post("/documents", data={"institution": "Other"},
                         files={"file": ("two.txt", b"Library hours are posted online.")}).json()
    assert first["sha256"] in {document["sha256"] for document in client.get("/documents").json()}
    answer = client.post("/ask", json={"question": "When is tuition due?", "institution": "Berkeley"}).json()
    assert [citation["document_id"] for citation in answer["citations"]] == [first["id"]]
    answer = client.post("/ask", json={"question": "When is tuition due?", "document_ids": [second["id"]]}).json()
    assert [citation["document_id"] for citation in answer["citations"]] == [second["id"]]
    answer = client.post("/ask", json={"question": "When is tuition due?", "document_ids": []}).json()
    assert answer["citations"] == []


def test_source_metadata_reaches_listing_citation_and_model_context(tmp_path: Path):
    client = TestClient(create_app(Settings(db_path=tmp_path / "metadata.sqlite3"), FakeProvider()))
    metadata = {
        "title": "Tuition Policy 2026",
        "source_url": "https://university.example.edu/policies/tuition.pdf",
        "institution": "Example University",
        "published_or_updated_date": "2026-07-01",
    }
    uploaded = client.post(
        "/documents", data=metadata,
        files={"file": ("tuition.txt", b"Tuition is due on August 15.")},
    )
    assert uploaded.status_code == 201
    assert {key: uploaded.json()[key] for key in metadata} == metadata
    listed = client.get("/documents").json()[0]
    assert {key: listed[key] for key in metadata} == metadata
    answer = client.post("/ask", json={"question": "When is tuition due?"}).json()
    citation = answer["citations"][0]
    assert {key: citation[key] for key in metadata} == metadata
    assert citation["page"] == 1
    assert "[1] Tuition Policy 2026, page 1" in format_sources([{
        "title": citation["title"], "page": citation["page"], "text": citation["excerpt"]
    }])
    assert "[1] Tuition Policy 2026 (2026-07-01), page 1" in format_sources([{
        "title": citation["title"], "published_or_updated_date": citation["published_or_updated_date"],
        "page": citation["page"], "text": citation["excerpt"],
    }])


def test_source_url_requires_http_or_https(tmp_path: Path):
    client = TestClient(create_app(Settings(db_path=tmp_path / "metadata.sqlite3"), FakeProvider()))
    response = client.post(
        "/documents", data={"source_url": "file:///etc/passwd"},
        files={"file": ("policy.txt", b"Tuition is due on August 15.")},
    )
    assert response.status_code == 422
    assert client.get("/documents").json() == []


def test_existing_database_is_migrated_without_losing_documents(tmp_path: Path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TABLE documents (
                id TEXT PRIMARY KEY, filename TEXT NOT NULL,
                sha256 TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        db.execute("INSERT INTO documents(id, filename, sha256) VALUES ('old-id', 'old.txt', 'old-hash')")
    store = Store(path)
    old = store.list_documents()[0]
    assert old["id"] == "old-id"
    assert old["title"] == "old.txt"
    assert old["source_url"] is None
    assert old["institution"] is None
    assert old["published_or_updated_date"] is None
    assert Store(path).list_documents()[0] == old
