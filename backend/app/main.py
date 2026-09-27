import hashlib
import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import AnyHttpUrl, BaseModel, Field, TypeAdapter, ValidationError

from .config import Settings
from .documents import chunk_pages, extract_pages
from .providers import GeminiProvider, ModelProvider, OpenAIProvider, ProviderError
from .store import Store


logger = logging.getLogger(__name__)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    institution: str | None = None
    document_ids: list[str] | None = None


class ErrorResponse(BaseModel):
    detail: str | list[dict[str, Any]]


class HealthResponse(BaseModel):
    status: Literal["ok"]


class DocumentResponse(BaseModel):
    id: str
    filename: str
    sha256: str | None = None
    title: str
    source_url: str | None = None
    institution: str | None = None
    published_or_updated_date: date | None = None
    extraction_warnings: list[str]
    chunk_count: int
    created_at: str | None = None


class CitationResponse(BaseModel):
    number: int
    document_id: str
    filename: str
    title: str
    source_url: str | None = None
    institution: str | None = None
    published_or_updated_date: date | None = None
    page: int
    excerpt: str


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]


PROVIDER_ERRORS = {429: {"model": ErrorResponse}, 502: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}


http_url = TypeAdapter(AnyHttpUrl)


def optional_text(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


def create_app(settings: Settings | None = None, provider: ModelProvider | None = None) -> FastAPI:
    settings = settings or Settings()
    chunk_pages([], settings.chunk_size, settings.chunk_overlap)
    store = Store(settings.db_path)
    app = FastAPI(title="CampusLens API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )

    def get_provider() -> ModelProvider:
        nonlocal provider
        if provider is None:
            if settings.model_provider == "openai":
                if not os.getenv("OPENAI_API_KEY"):
                    raise HTTPException(status_code=503, detail="Set OPENAI_API_KEY for the selected model provider")
                provider = OpenAIProvider(settings.embedding_model, settings.answer_model)
            elif settings.model_provider == "gemini":
                api_key = os.getenv("GEMINI_API_KEY")
                if not api_key:
                    raise HTTPException(status_code=503, detail="Set GEMINI_API_KEY for the selected model provider")
                provider = GeminiProvider(
                    api_key, settings.gemini_embedding_model,
                    settings.gemini_answer_model, settings.gemini_embedding_dimensions,
                )
            else:
                raise HTTPException(status_code=503, detail="CAMPUSLENS_PROVIDER must be 'gemini' or 'openai'")
        return provider

    def model_call(method: str, *args):
        try:
            return getattr(get_provider(), method)(*args)
        except HTTPException:
            raise
        except ProviderError as exc:
            messages = {
                "authentication": (503, "Model service authentication failed; check the selected API key"),
                "rate_limit": (429, "Model service rate limit reached; try again later"),
                "configuration": (503, "Model service rejected its configuration; check model names"),
            }
            status, detail = messages.get(exc.kind, (502, "Model service request failed"))
            raise HTTPException(status_code=status, detail=detail) from exc
        except Exception as exc:
            logger.exception("Unexpected model provider failure during %s", method)
            raise HTTPException(status_code=502, detail="Model service request failed") from exc

    @app.get("/health", response_model=HealthResponse)
    def health():
        return {"status": "ok"}

    @app.get("/documents", response_model=list[DocumentResponse])
    def list_documents():
        return store.list_documents()

    def ingest_document(
        file: UploadFile,
        title: str | None,
        source_url: str | None,
        institution: str | None,
        published_or_updated_date: date | None,
        document_id: str | None = None,
    ):
        if document_id and not store.get(document_id):
            raise HTTPException(status_code=404, detail="Document not found")
        filename = Path(file.filename or "").name
        if Path(filename).suffix.lower() not in {".pdf", ".txt"}:
            raise HTTPException(status_code=415, detail="Only .pdf and .txt files are supported")
        title = optional_text(title)
        institution = optional_text(institution)
        source_url = optional_text(source_url)
        if source_url:
            try:
                source_url = str(http_url.validate_python(source_url))
            except ValidationError as exc:
                raise HTTPException(status_code=422, detail="source_url must be an HTTP(S) URL") from exc
        data = file.file.read(settings.max_upload_bytes + 1)
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
        sha256 = hashlib.sha256(data).hexdigest()
        if existing := store.by_hash(sha256):
            raise HTTPException(status_code=409, detail=f"Document already uploaded: {existing['id']}")
        try:
            extraction = extract_pages(filename, data)
            chunks = chunk_pages(extraction.pages, settings.chunk_size, settings.chunk_overlap)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not chunks:
            raise HTTPException(status_code=422, detail="No extractable text found; scanned PDFs need OCR")
        embeddings = []
        for start in range(0, len(chunks), 64):
            embeddings.extend(model_call("embed_documents", [text for _, text in chunks[start:start + 64]]))
        metadata = dict(
            title=title, source_url=source_url, institution=institution,
            published_or_updated_date=published_or_updated_date.isoformat() if published_or_updated_date else None,
            extraction_warnings=extraction.warnings,
            embedding_profile=settings.embedding_profile,
        )
        if document_id:
            return store.replace(document_id, filename, sha256, chunks, embeddings, **metadata)
        return store.add(filename, sha256, chunks, embeddings, **metadata)

    @app.post(
        "/documents", status_code=201, response_model=DocumentResponse,
        responses={409: {"model": ErrorResponse}, 413: {"model": ErrorResponse},
                   415: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, **PROVIDER_ERRORS},
    )
    def upload_document(
        file: UploadFile = File(...),
        title: str | None = Form(None),
        source_url: str | None = Form(None),
        institution: str | None = Form(None),
        published_or_updated_date: date | None = Form(None),
    ):
        return ingest_document(file, title, source_url, institution, published_or_updated_date)

    @app.put(
        "/documents/{document_id}", response_model=DocumentResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse},
                   413: {"model": ErrorResponse}, 415: {"model": ErrorResponse},
                   422: {"model": ErrorResponse}, **PROVIDER_ERRORS},
    )
    def replace_document(
        document_id: str,
        file: UploadFile = File(...),
        title: str | None = Form(None),
        source_url: str | None = Form(None),
        institution: str | None = Form(None),
        published_or_updated_date: date | None = Form(None),
    ):
        return ingest_document(file, title, source_url, institution, published_or_updated_date, document_id)

    @app.delete("/documents/{document_id}", status_code=204, responses={404: {"model": ErrorResponse}})
    def delete_document(document_id: str):
        if not store.delete(document_id):
            raise HTTPException(status_code=404, detail="Document not found")

    @app.post(
        "/ask", response_model=AskResponse,
        responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, **PROVIDER_ERRORS},
    )
    def ask(request: AskRequest):
        if not store.list_documents():
            return {"answer": "Upload a document first.", "citations": []}
        if store.embedding_profiles() != {settings.embedding_profile}:
            raise HTTPException(
                status_code=409,
                detail="Documents use a different embedding model; replace or re-upload them with the selected provider",
            )
        sources = store.search(
            request.question, model_call("embed_query", request.question),
            institution=request.institution, document_ids=request.document_ids,
        )
        if not sources:
            return {"answer": "I could not find that in the uploaded documents.", "citations": []}
        answer = model_call("answer", request.question, sources)
        used = {int(number) for number in re.findall(r"\[(\d+)\]", answer)}
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

    return app


app = create_app()
