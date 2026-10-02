"""Access control and bounded bodies before multipart parsing or provider calls."""

import base64
import binascii
import hmac
import json
import logging
import time
from collections import deque
from uuid import uuid4

from starlette.responses import JSONResponse

logger = logging.getLogger("campuslens.requests")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.propagate = False


class AccessMiddleware:
    def __init__(self, app, settings):
        self.app = app
        self.settings = settings
        # Global budget, deliberately independent of spoofable IP headers.
        self.requests = deque()

    def authenticated(self, headers):
        try:
            scheme, encoded = headers.get(b"authorization", b"").split(b" ", 1)
            if scheme.lower() != b"basic":
                return False
            username, password = base64.b64decode(encoded, validate=True).split(b":", 1)
            return hmac.compare_digest(username, self.settings.auth_username.encode()) & hmac.compare_digest(
                password, self.settings.auth_password.encode()
            )
        except (ValueError, binascii.Error):
            return False

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.monotonic()
        request_id = uuid4().hex
        status = 500
        response_started = False
        headers = dict(scope["headers"])
        path = scope["path"]

        async def logged_send(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                message["headers"] = list(message["headers"]) + [(b"x-request-id", request_id.encode())]
            await send(message)

        async def reject(code, detail, extra=None):
            await JSONResponse({"detail": detail}, status_code=code, headers=extra)(scope, receive, logged_send)

        try:
            if path != "/health" and scope["method"] != "OPTIONS":
                if self.settings.auth_username and not self.authenticated(headers):
                    return await reject(401, "Authentication required", {"WWW-Authenticate": 'Basic realm="CampusLens", charset="UTF-8"'})
                if scope["method"] in {"POST", "PUT", "DELETE"}:
                    now = time.monotonic()
                    while self.requests and self.requests[0] <= now - 60:
                        self.requests.popleft()
                    if len(self.requests) >= self.settings.requests_per_minute:
                        return await reject(429, "Request limit reached. Try again in a minute.", {"Retry-After": "60"})
                    self.requests.append(now)
            if scope["method"] in {"POST", "PUT", "PATCH"}:
                limit = self.settings.max_upload_bytes + 65536 if path.startswith("/documents") else 16384
                try:
                    length = int(headers.get(b"content-length", b"0"))
                except ValueError:
                    return await reject(400, "Invalid Content-Length")
                if length < 0 or length > limit:
                    return await reject(413, "Request body exceeds the size limit")
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > limit:
                        return await reject(413, "Request body exceeds the size limit")
                    if not message.get("more_body", False):
                        break
                delivered = False

                async def replay():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()

                await self.app(scope, replay, logged_send)
            else:
                await self.app(scope, receive, logged_send)
        except Exception as exc:
            # Never log request bodies, credentials, provider messages or traces.
            logger.error(json.dumps({"event": "request_exception", "request_id": request_id, "type": type(exc).__name__}))
            if not response_started:
                await reject(500, "Internal server error")
            else:
                raise
        finally:
            logger.info(json.dumps({"event": "request", "request_id": request_id,
                "method": scope["method"], "route": "documents" if path.startswith("/documents") else path if path in {"/health", "/ask"} else "other",
                "status": status, "duration_ms": round((time.monotonic() - started) * 1000, 2)}))
