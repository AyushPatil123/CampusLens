import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security import AccessMiddleware
from test_api import FakeProvider

AUTH = ("demo", "a-long-test-password-123")


def settings(tmp_path, **kwargs):
    return Settings(db_path=tmp_path / "fresh.sqlite3", deployment_mode="public",
                    auth_username=AUTH[0], auth_password=AUTH[1], **kwargs)


def test_public_mode_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="Public mode"):
        create_app(Settings(db_path=tmp_path / "fail.sqlite3", deployment_mode="public"))
    assert not (tmp_path / "fail.sqlite3").exists()


def test_all_routes_protected_and_health_public(tmp_path):
    client = TestClient(create_app(settings(tmp_path), FakeProvider()))
    assert client.get("/health").status_code == 200
    for method, path in [("GET", "/documents"), ("GET", "/docs"), ("GET", "/openapi.json"),
                         ("POST", "/ask"), ("POST", "/documents"),
                         ("PUT", "/documents/id"), ("DELETE", "/documents/id")]:
        response = client.request(method, path)
        assert response.status_code == 401
        assert "Basic" in response.headers["www-authenticate"]
    assert client.get("/access", auth=("demo", "wrong")).status_code == 401
    assert client.get("/access", headers={"Authorization": "Basic !!!"}).status_code == 401
    assert client.get("/documents", auth=AUTH).json() == []


def test_global_budget_and_no_provider_calls_without_auth(tmp_path):
    class CountingProvider(FakeProvider):
        calls = 0

        def embed_documents(self, texts):
            self.calls += 1
            return super().embed_documents(texts)

    provider = CountingProvider()
    client = TestClient(create_app(settings(tmp_path, requests_per_minute=2), provider))
    assert client.post("/documents", files={"file": ("a.txt", b"Tuition August 15")}).status_code == 401
    assert provider.calls == 0
    assert client.post("/documents", auth=AUTH, files={"file": ("a.txt", b"Tuition August 15")}).status_code == 201
    assert client.post("/ask", auth=AUTH, json={"question": "When is tuition due?"}).status_code == 200
    rejected = client.post("/ask", auth=AUTH, headers={"X-Forwarded-For": "new-ip"}, json={"question": "When is tuition due?"})
    assert rejected.status_code == 429
    assert rejected.headers["retry-after"] == "60"
    assert client.get("/health").status_code == 200
    # A fresh process opens the same persistent database.
    restarted = TestClient(create_app(settings(tmp_path), FakeProvider()))
    assert len(restarted.get("/documents", auth=AUTH).json()) == 1


def test_streamed_body_limit_without_content_length(tmp_path):
    called = False

    async def downstream(scope, receive, send):
        nonlocal called
        called = True

    messages = iter([{"type": "http.request", "body": b"x" * 9000, "more_body": True},
                     {"type": "http.request", "body": b"y" * 9000, "more_body": False}])
    sent = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    middleware = AccessMiddleware(downstream, Settings(db_path=tmp_path / "unused"))
    asyncio.run(middleware({"type": "http", "method": "POST", "path": "/ask", "headers": []}, receive, send))
    assert sent[0]["status"] == 413
    assert not called


def test_errors_are_sanitized_and_logs_exclude_secrets(tmp_path, monkeypatch):
    from app import security
    logs = []
    monkeypatch.setattr(security.logger, "info", logs.append)
    monkeypatch.setattr(security.logger, "error", logs.append)
    app = create_app(settings(tmp_path), FakeProvider())

    @app.get("/broken")
    def broken():
        raise RuntimeError("private-key-do-not-log")

    response = TestClient(app).get("/broken", auth=AUTH)
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert response.headers["x-request-id"]
    assert "private-key" not in "".join(logs)
    assert AUTH[1] not in "".join(logs)
    assert json.loads(logs[-1])["status"] == 500
