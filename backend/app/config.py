import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    deployment_mode: str = os.getenv("CAMPUSLENS_MODE", "local")
    auth_username: str = os.getenv("CAMPUSLENS_AUTH_USERNAME", "")
    auth_password: str = os.getenv("CAMPUSLENS_AUTH_PASSWORD", "")
    requests_per_minute: int = int(os.getenv("CAMPUSLENS_REQUESTS_PER_MINUTE", "10"))
    db_path: Path = Path(os.getenv("CAMPUSLENS_DB", "data/campuslens.sqlite3"))
    model_provider: str = os.getenv("CAMPUSLENS_PROVIDER", "gemini").strip().lower()
    embedding_model: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    answer_model: str = os.getenv("OPENAI_ANSWER_MODEL", "gpt-4.1-mini")
    gemini_embedding_model: str = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    gemini_answer_model: str = os.getenv("GEMINI_ANSWER_MODEL", "gemini-3.8-flash")
    gemini_embedding_dimensions: int = int(os.getenv("GEMINI_EMBEDDING_DIMENSIONS", "768"))
    max_upload_bytes: int = 10 * 1024 * 1024
    chunk_size: int = int(os.getenv("CAMPUSLENS_CHUNK_SIZE", "900"))
    chunk_overlap: int = int(os.getenv("CAMPUSLENS_CHUNK_OVERLAP", "120"))
    cors_origins: tuple[str, ...] = tuple(
        origin.strip() for origin in os.getenv(
            "CAMPUSLENS_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",") if origin.strip()
    )

    @property
    def embedding_profile(self) -> str:
        if self.model_provider == "gemini":
            return f"gemini:{self.gemini_embedding_model}:{self.gemini_embedding_dimensions}"
        return f"openai:{self.embedding_model}"
