from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers import GeminiProvider, ProviderError


class FakeModels:
    def __init__(self):
        self.embed_calls = []
        self.answer_call = None

    def embed_content(self, model, contents, config):
        self.embed_calls.append((model, contents, config))
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0, 0.0]) for _ in contents])

    def generate_content(self, model, contents, config):
        self.answer_call = (model, contents, config)
        return SimpleNamespace(text="The deadline is August 15 [1].")


class FakeProvider:
    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0]

    def answer(self, question, sources):
        return "The deadline is August 15 [1]."


class FailingProvider(FakeProvider):
    def embed_documents(self, texts):
        raise RuntimeError("internal-secret-should-not-appear")


class AuthFailingProvider(FakeProvider):
    def embed_documents(self, texts):
        raise ProviderError("authentication")


def test_gemini_provider_uses_distinct_retrieval_tasks_and_cited_prompt():
    models = FakeModels()
    provider = GeminiProvider.__new__(GeminiProvider)
    provider.client = SimpleNamespace(models=models)
    provider.embedding_model = "gemini-embedding-001"
    provider.answer_model = "gemini-3.8-flash"
    provider.dimensions = 768

    assert provider.embed_documents(["policy text", "other text"]) == [[1.0, 0.0], [1.0, 0.0]]
    assert provider.embed_query("deadline") == [1.0, 0.0]
    assert provider.embed_queries(["deadline one", "deadline two"]) == [[1.0, 0.0], [1.0, 0.0]]
    assert [call[2].task_type for call in models.embed_calls] == [
        "RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY", "RETRIEVAL_QUERY",
    ]
    assert all(call[2].output_dimensionality == 768 for call in models.embed_calls)
    answer = provider.answer("When is the deadline?", [{"title": "Rules", "page": 2, "text": "August 15"}])
    assert "[1]" in answer
    assert "[1] Rules, page 2" in models.answer_call[1]
    assert "only the supplied excerpts" in models.answer_call[2].system_instruction


def test_response_schemas_cors_and_safe_provider_errors(tmp_path):
    settings = Settings(db_path=tmp_path / "api.sqlite3")
    app = create_app(settings, FailingProvider())
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/documents"]["post"]["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith("DocumentResponse")
    assert schema["paths"]["/ask"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("AskResponse")
    assert schema["paths"]["/ask"]["post"]["responses"]["502"]["content"]["application/json"]["schema"]["$ref"].endswith("ErrorResponse")
    preflight = client.options(
        "/ask", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
    )
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"
    blocked = client.options(
        "/ask", headers={"Origin": "https://elsewhere.example", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in blocked.headers
    response = client.post("/documents", files={"file": ("policy.txt", b"The deadline is August 15.")})
    assert response.status_code == 502
    assert response.json() == {"detail": "Model service request failed"}
    assert "internal-secret" not in response.text


def test_missing_or_invalid_provider_config_returns_clear_errors(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    missing = TestClient(create_app(Settings(db_path=tmp_path / "missing.sqlite3")))
    response = missing.post("/documents", files={"file": ("policy.txt", b"The deadline is August 15.")})
    assert response.status_code == 503
    assert response.json() == {"detail": "Set GEMINI_API_KEY for the selected model provider"}

    invalid = TestClient(create_app(Settings(db_path=tmp_path / "invalid.sqlite3", model_provider="invalid")))
    response = invalid.post("/documents", files={"file": ("policy.txt", b"The deadline is August 15.")})
    assert response.status_code == 503
    assert "CAMPUSLENS_PROVIDER" in response.json()["detail"]

    auth = TestClient(create_app(Settings(db_path=tmp_path / "auth.sqlite3"), AuthFailingProvider()))
    response = auth.post("/documents", files={"file": ("policy.txt", b"The deadline is August 15.")})
    assert response.status_code == 503
    assert response.json() == {"detail": "Model service authentication failed; check the selected API key"}


def test_switching_embedding_models_requires_reindex(tmp_path):
    path = tmp_path / "profile.sqlite3"
    gemini = TestClient(create_app(Settings(db_path=path, model_provider="gemini"), FakeProvider()))
    uploaded = gemini.post("/documents", files={"file": ("policy.txt", b"The deadline is August 15.")})
    assert uploaded.status_code == 201
    document_id = uploaded.json()["id"]
    openai = TestClient(create_app(Settings(db_path=path, model_provider="openai"), FakeProvider()))
    response = openai.post("/ask", json={"question": "When is the deadline?"})
    assert response.status_code == 409
    assert "replace or re-upload" in response.json()["detail"]
    replaced = openai.put(
        f"/documents/{document_id}", files={"file": ("policy.txt", b"The deadline is August 15, according to the new policy.")}
    )
    assert replaced.status_code == 200
    assert openai.post("/ask", json={"question": "When is the deadline?"}).status_code == 200
