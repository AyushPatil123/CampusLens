from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings
from .documents import chunk_pages
from .errors import ServiceError
from .model_gateway import ModelGateway
from .providers import ModelProvider
from .routes import create_router
from .services import DocumentService
from .store import Store


def create_app(settings: Settings | None = None, provider: ModelProvider | None = None) -> FastAPI:
    settings = settings or Settings()
    chunk_pages([], settings.chunk_size, settings.chunk_overlap)
    service = DocumentService(settings, Store(settings.db_path), ModelGateway(settings, provider))
    app = FastAPI(title="CampusLens API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(ServiceError)
    def service_error(_request: Request, exc: ServiceError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    app.include_router(create_router(service))
    return app


app = create_app()
