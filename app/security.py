"""Security middleware: headers, request ids, body size cap, rate limits and safe errors.

Pure ASGI middleware, so streaming bodies and every response (including 413s) are covered.
"""

import logging
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings

logger = logging.getLogger("toran.security")

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com",
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": CSP,
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(self), camera=(), microphone=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

DOCS_PATHS = ("/docs", "/openapi.json")
"""Swagger UI loads its own CDN scripts, so the CSP is relaxed only there (never in production,
where these paths are switched off)."""

STATIC_CACHE = "public, max-age=300"
"""Short, because file names carry no content hash and a deploy must reach users quickly."""

GENERIC_ERROR = "Something went wrong on our side. Please try again."
TOO_MANY = "Too many requests. Please wait a minute and try again."
TOO_LARGE = "That request is too large."


def client_ip(request: Request) -> str:
    """The visitor's IP: the first x-forwarded-for entry (set by Vercel's edge), else the peer."""
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else "unknown"


def llm_limit() -> str:
    """Per-IP limit for routes that call Gemini, read from settings at request time."""
    return get_settings().rate_limit_llm


limiter = Limiter(key_func=client_ip, headers_enabled=False)


class SecurityHeadersMiddleware:
    """Adds security headers and an X-Request-ID to every response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex[:12]
        scope.setdefault("state", {})["request_id"] = request_id
        relaxed = scope["path"].startswith(DOCS_PATHS) and not get_settings().is_production

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                for name, value in SECURITY_HEADERS.items():
                    if relaxed and name == "Content-Security-Policy":
                        continue
                    headers.append((name.lower().encode(), value.encode()))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    """Rejects request bodies larger than MAX_BODY_BYTES with 413, before any route runs."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = get_settings().max_body_bytes
        declared = dict(scope.get("headers", [])).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _too_large(scope, receive, send)
            return

        body = b""
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            more = message.get("more_body", False)
            if len(body) > limit:
                await _too_large(scope, receive, send)
                return

        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
    response = JSONResponse({"detail": TOO_LARGE}, status_code=413)
    await response(scope, receive, send)


class CachedStaticFiles(StaticFiles):
    """Static files with a Cache-Control header."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = STATIC_CACHE
        return response


def _with_headers(response: Response, request: Request) -> Response:
    """For 500s only: Starlette renders them outside all middleware, so add headers here."""
    for name, value in SECURITY_HEADERS.items():
        response.headers[name] = value
    response.headers["X-Request-ID"] = getattr(request.state, "request_id", "unknown")
    return response


async def _rate_limited(request: Request, exc: Exception) -> Response:
    """Runs inside the middleware stack, so the security headers are added there."""
    return JSONResponse({"detail": TOO_MANY}, status_code=429)


async def _unexpected(request: Request, exc: Exception) -> Response:
    """No stack trace or exception text reaches the client; the log has both, with the id."""
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error("unhandled_error request_id=%s path=%s", request_id, request.url.path,
                 exc_info=exc)
    body = {"detail": GENERIC_ERROR, "request_id": request_id}
    return _with_headers(JSONResponse(body, status_code=500), request)


def install(app: FastAPI) -> None:
    """Wire all of the above into the app. Outermost first: headers, body limit, gzip."""
    app.state.limiter = limiter
    handlers: MutableMapping[Any, Callable[[Request, Exception], Awaitable[Response]]] = {
        RateLimitExceeded: _rate_limited,
        Exception: _unexpected,
    }
    for exc_class, handler in handlers.items():
        app.add_exception_handler(exc_class, handler)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
