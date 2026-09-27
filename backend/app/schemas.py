from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


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
