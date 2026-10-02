import hashlib
import re
from datetime import date
from pathlib import Path

from fastapi import UploadFile
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

from .config import Settings
from .documents import chunk_pages, extract_pages
from .errors import ServiceError
from .model_gateway import ModelGateway
from .retrieval import RetrievalMode
from .store import Store


http_url = TypeAdapter(AnyHttpUrl)


def optional_text(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


class DocumentService:
    """Coordinate extraction, indexing, retrieval, and cited answers."""

    def __init__(self, settings: Settings, store: Store, models: ModelGateway):
        self.settings = settings
        self.store = store
        self.models = models

    def list_documents(self) -> list[dict]:
        return self.store.list_documents()

    def delete(self, document_id: str) -> None:
        if not self.store.delete(document_id):
            raise ServiceError(404, "Document not found")

    def ingest(
        self, file: UploadFile, title: str | None, source_url: str | None,
        institution: str | None, published_or_updated_date: date | None,
        document_id: str | None = None,
    ) -> dict:
        if document_id and not self.store.get(document_id):
            raise ServiceError(404, "Document not found")
        filename = Path(file.filename or "").name
        if Path(filename).suffix.lower() not in {".pdf", ".txt"}:
            raise ServiceError(415, "Only .pdf and .txt files are supported")
        title = optional_text(title)
        institution = optional_text(institution)
        source_url = optional_text(source_url)
        if source_url:
            try:
                source_url = str(http_url.validate_python(source_url))
            except ValidationError as exc:
                raise ServiceError(422, "source_url must be an HTTP(S) URL") from exc
        data = file.file.read(self.settings.max_upload_bytes + 1)
        if len(data) > self.settings.max_upload_bytes:
            raise ServiceError(413, "File exceeds 10 MB limit")
        sha256 = hashlib.sha256(data).hexdigest()
        if existing := self.store.by_hash(sha256):
            raise ServiceError(409, f"Document already uploaded: {existing['id']}")
        try:
            extraction = extract_pages(filename, data)
            chunks = chunk_pages(extraction.pages, self.settings.chunk_size, self.settings.chunk_overlap)
        except ValueError as exc:
            raise ServiceError(422, str(exc)) from exc
        if not chunks:
            raise ServiceError(422, "No extractable text found; scanned PDFs need OCR")
        embeddings = []
        for start in range(0, len(chunks), 64):
            embeddings.extend(self.models.call("embed_documents", [text for _, text in chunks[start:start + 64]]))
        metadata = dict(
            title=title, source_url=source_url, institution=institution,
            published_or_updated_date=published_or_updated_date.isoformat() if published_or_updated_date else None,
            extraction_warnings=extraction.warnings,
            embedding_profile=self.settings.embedding_profile,
        )
        if document_id:
            return self.store.replace(document_id, filename, sha256, chunks, embeddings, **metadata)
        return self.store.add(filename, sha256, chunks, embeddings, **metadata)

    def ask(
        self, question: str, institution: str | None = None,
        document_ids: list[str] | None = None,
        retrieval_mode: RetrievalMode = "hybrid_diverse",
    ) -> dict:
        if not self.store.list_documents():
            return {"answer": "Upload a document first.", "citations": []}
        if self.store.embedding_profiles() != {self.settings.embedding_profile}:
            raise ServiceError(
                409, "Documents use a different embedding model; replace or re-upload them with the selected provider",
            )
        sources = self.store.search(
            question, self.models.call("embed_query", question),
            institution=institution, document_ids=document_ids, mode=retrieval_mode,
        )
        if not sources:
            return {"answer": "I could not find that in the uploaded documents.", "citations": []}
        answer = self.models.call("answer", question, sources)
        used = {int(number) for number in re.findall(r"\[(\d+)\]", answer)}
        if any(number < 1 or number > len(sources) for number in used):
            return {"answer": "I could not verify an answer from the uploaded documents.", "citations": []}
        citations = [
            {"number": index, "document_id": source["document_id"], "filename": source["filename"],
             "title": source["title"], "source_url": source["source_url"],
             "institution": source["institution"],
             "published_or_updated_date": source["published_or_updated_date"],
             "page": source["page"], "excerpt": source["text"]}
            for index, source in enumerate(sources, 1) if index in used
        ]
        if not citations and answer != "I could not find that in the uploaded documents.":
            return {"answer": "I could not verify an answer from the uploaded documents.", "citations": []}
        return {"answer": answer, "citations": citations}
