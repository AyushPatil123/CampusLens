from io import BytesIO
import json
import sqlite3
import httpx

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.config import Settings
from app.documents import chunk_pages, extract_pages
from app.main import create_app
from app.store import Store
from scripts.ingest_corpus import load_manifest, sync_corpus


def make_pdf(last_text: str = "Tuition is due on August 15") -> bytes:
    writer = PdfWriter()
    for text in ("Welcome to campus", None, last_text):
        page = writer.add_blank_page(width=612, height=792)
        if text:
            font = DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
            })
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class FakeProvider:
    def embed_documents(self, texts):
        return [[float("tuition" in text.lower()), 1.0] for text in texts]

    def embed_query(self, text):
        return self.embed_documents([text])[0]

    def answer(self, question, sources):
        return "Tuition is due on August 15 [1]."


class FailingProvider(FakeProvider):
    def embed_documents(self, texts):
        if any("replacement" in text.lower() for text in texts):
            raise RuntimeError("Embedding failed")
        return super().embed_documents(texts)


def test_pdf_pages_warnings_and_citation(tmp_path):
    data = make_pdf()
    extraction = extract_pages("policy.pdf", data)
    assert [number for number, _ in extraction.pages] == [1, 2, 3]
    assert extraction.pages[0][1].strip() == "Welcome to campus"
    assert extraction.pages[2][1].strip() == "Tuition is due on August 15"
    assert extraction.warnings == ["Page 2 has no extractable text; it may need OCR."]

    client = TestClient(create_app(Settings(db_path=tmp_path / "pdf.sqlite3"), FakeProvider()))
    upload = client.post("/documents", files={"file": ("policy.pdf", data, "application/pdf")})
    assert upload.status_code == 201
    assert upload.json()["extraction_warnings"] == extraction.warnings
    assert client.get("/documents").json()[0]["extraction_warnings"] == extraction.warnings
    answer = client.post("/ask", json={"question": "When is tuition due?"}).json()
    assert answer["citations"][0]["page"] == 3


def test_invalid_text_empty_scan_and_size_limit(tmp_path):
    client = TestClient(create_app(Settings(db_path=tmp_path / "limits.sqlite3", max_upload_bytes=4), FakeProvider()))
    assert client.post("/documents", files={"file": ("large.txt", b"12345")}).status_code == 413
    assert client.post("/documents", files={"file": ("bad.txt", b"\xff")}).status_code == 422
    assert client.post("/documents", files={"file": ("empty.txt", b"  ")}).status_code == 422
    assert client.get("/documents").json() == []

    scanned = PdfWriter()
    scanned.add_blank_page(width=612, height=792)
    output = BytesIO()
    scanned.write(output)
    other = TestClient(create_app(Settings(db_path=tmp_path / "scan.sqlite3"), FakeProvider()))
    response = other.post("/documents", files={"file": ("scan.pdf", output.getvalue(), "application/pdf")})
    assert response.status_code == 422
    assert "OCR" in response.json()["detail"]


def test_chunk_settings_and_overlap():
    pages = [(1, "alpha beta gamma delta epsilon zeta")]
    chunks = chunk_pages(pages, size=18, overlap=6)
    assert len(chunks) > 1
    assert all(page == 1 for page, _ in chunks)
    assert "gamma" in chunks[1][1]
    with pytest.raises(ValueError):
        chunk_pages(pages, size=10, overlap=10)


def test_failed_embedding_leaves_original_document(tmp_path):
    path = tmp_path / "failure.sqlite3"
    client = TestClient(create_app(Settings(db_path=path), FailingProvider()), raise_server_exceptions=False)
    first = client.post("/documents", files={"file": ("policy.txt", b"Original tuition policy.")})
    assert first.status_code == 201
    document_id = first.json()["id"]
    failed = client.put(
        f"/documents/{document_id}",
        files={"file": ("policy.txt", b"Replacement tuition policy.")},
    )
    assert failed.status_code == 502
    assert client.get("/documents").json()[0]["id"] == document_id
    assert Store(path).search("Original", [1.0, 1.0])[0]["text"] == "Original tuition policy."
    assert client.post("/documents", files={"file": ("new.txt", b"Replacement tuition policy.")}).status_code == 502
    assert len(client.get("/documents").json()) == 1


def test_replace_swaps_indexes_and_rolls_back_database_error(tmp_path):
    path = tmp_path / "replace.sqlite3"
    store = Store(path)
    original = store.add("rules.txt", "original-hash", [(1, "Old appeals deadline")], [[1.0, 0.0]])
    document_id = original["id"]
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TRIGGER fail_replacement BEFORE INSERT ON chunks
               WHEN NEW.text LIKE '%blocked%' BEGIN SELECT RAISE(ABORT, 'test failure'); END"""
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.replace(document_id, "rules.txt", "blocked-hash", [(2, "blocked new rule")], [[0.0, 1.0]])
    assert store.get(document_id)["sha256"] == "original-hash"
    assert store.search("appeals", [1.0, 0.0])[0]["text"] == "Old appeals deadline"
    with sqlite3.connect(path) as db:
        db.execute("DROP TRIGGER fail_replacement")
    replaced = store.replace(document_id, "rules.txt", "new-hash", [(2, "New appeals deadline")], [[0.0, 1.0]])
    assert replaced["id"] == document_id
    assert store.get(document_id)["sha256"] == "new-hash"
    assert [row["text"] for row in store.search("appeals", [0.0, 1.0])] == ["New appeals deadline"]


def test_replace_endpoint_preserves_id_and_source_metadata(tmp_path):
    path = tmp_path / "api-replace.sqlite3"
    client = TestClient(create_app(Settings(db_path=path), FakeProvider()))
    first = client.post(
        "/documents",
        data={"title": "Student Rules", "source_url": "https://example.edu/rules.pdf"},
        files={"file": ("rules.txt", b"Old appeals deadline.")},
    )
    assert first.status_code == 201
    document_id = first.json()["id"]
    updated = client.put(
        f"/documents/{document_id}",
        files={"file": ("rules.txt", b"New appeals deadline.")},
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == document_id
    assert updated.json()["title"] == "Student Rules"
    assert updated.json()["source_url"] == "https://example.edu/rules.pdf"
    assert len(client.get("/documents").json()) == 1
    assert [row["text"] for row in Store(path).search("appeals", [1.0, 1.0])] == ["New appeals deadline."]


def test_corpus_sync_adds_skips_and_replaces_by_source_hash(tmp_path):
    url = "https://grad.berkeley.edu/wp-content/uploads/archive/policy.pdf"
    manifest = [{
        "title": "Graduate Policy", "source_url": url,
        "institution": "University of California, Berkeley",
        "published_or_updated_date": "2022-01-01", "file_type": "pdf", "retrieved_at": "2026-09-27",
    }]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    entries = load_manifest(path)
    current = [make_pdf()]
    source = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, content=current[0], request=request,
    )))
    api = TestClient(create_app(Settings(db_path=tmp_path / "corpus.sqlite3"), FakeProvider()))
    cache = tmp_path / "cache"
    assert sync_corpus(entries, api, source, cache)["added"] == 1
    first = api.get("/documents").json()[0]
    assert first["source_url"] == url
    assert first["sha256"]
    assert sync_corpus(entries, api, source, cache)["unchanged"] == 1
    assert sync_corpus(entries, api, source, cache, force=True)["replaced"] == 1
    assert api.get("/documents").json()[0]["id"] == first["id"]
    current[0] = make_pdf("Tuition is due on September 1")
    assert sync_corpus(entries, api, source, cache)["replaced"] == 1
    updated = api.get("/documents").json()[0]
    assert updated["id"] == first["id"]
    assert updated["sha256"] != first["sha256"]
    assert Store(tmp_path / "corpus.sqlite3").search("September", [1.0, 1.0])[0]["page"] == 3


def test_corpus_sync_retries_rate_limited_upload(tmp_path, monkeypatch):
    url = "https://grad.berkeley.edu/wp-content/uploads/archive/policy.pdf"
    entry = {
        "title": "Graduate Policy", "source_url": url,
        "institution": "University of California, Berkeley",
        "published_or_updated_date": "2022-01-01", "file_type": "pdf", "retrieved_at": "2026-09-27",
    }
    source = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, content=make_pdf(), request=request,
    )))
    client = TestClient(create_app(Settings(db_path=tmp_path / "retry.sqlite3"), FakeProvider()))

    class RateLimitedOnce:
        calls = 0

        def get(self, *args, **kwargs):
            return client.get(*args, **kwargs)

        def post(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return httpx.Response(429, request=httpx.Request("POST", "http://testserver/documents"))
            return client.post(*args, **kwargs)

    monkeypatch.setattr("scripts.ingest_corpus.time.sleep", lambda seconds: None)
    api = RateLimitedOnce()
    assert sync_corpus([entry], api, source, tmp_path / "cache", rate_limit_retries=1)["added"] == 1
    assert api.calls == 2
