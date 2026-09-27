from datetime import date

from fastapi import APIRouter, File, Form, UploadFile

from .schemas import AskRequest, AskResponse, DocumentResponse, ErrorResponse, HealthResponse
from .services import DocumentService


PROVIDER_ERRORS = {429: {"model": ErrorResponse}, 502: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}


def create_router(service: DocumentService) -> APIRouter:
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse)
    def health():
        return {"status": "ok"}

    @router.get("/documents", response_model=list[DocumentResponse])
    def list_documents():
        return service.list_documents()

    @router.post(
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
        return service.ingest(file, title, source_url, institution, published_or_updated_date)

    @router.put(
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
        return service.ingest(file, title, source_url, institution, published_or_updated_date, document_id)

    @router.delete("/documents/{document_id}", status_code=204, responses={404: {"model": ErrorResponse}})
    def delete_document(document_id: str):
        service.delete(document_id)

    @router.post(
        "/ask", response_model=AskResponse,
        responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, **PROVIDER_ERRORS},
    )
    def ask(request: AskRequest):
        return service.ask(request.question, request.institution, request.document_ids)

    return router
