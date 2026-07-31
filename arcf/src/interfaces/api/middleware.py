"""ASGI-level middleware for the Secure Fast Path.

RequestSizeLimitMiddleware rejects declared-oversized bodies immediately
via Content-Length (the reliable, fast path for honest clients) and also
caps actual bytes received as a request streams in (defense-in-depth
against a client that lies about, or omits, Content-Length — that path
can't be exercised through TestClient/httpx, which always sends an
accurate header, but protects a real deployment against a raw ASGI
client that doesn't).

TracingMiddleware wraps every request in a span and stamps the response
with X-Trace-Id, fulfilling the "trace per request" deliverable.
"""

from collections.abc import Awaitable, Callable

from opentelemetry.trace import Tracer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from shared.errors import RequestTooLargeError


class RequestSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        declared_length_raw = headers.get(b"content-length")
        if declared_length_raw is not None:
            try:
                declared_length = int(declared_length_raw)
            except ValueError:
                declared_length = None
            if declared_length is not None and declared_length > self.max_bytes:
                response = JSONResponse(
                    {"detail": f"Request body exceeds {self.max_bytes} byte limit"},
                    status_code=413,
                )
                await response(scope, receive, send)
                return

        total = 0

        async def limited_receive() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b"") or b"")
                if total > self.max_bytes:
                    raise RequestTooLargeError()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestTooLargeError:
            response = JSONResponse(
                {"detail": f"Request body exceeds {self.max_bytes} byte limit"},
                status_code=413,
            )
            await response(scope, receive, send)


class TracingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, tracer: Tracer) -> None:
        super().__init__(app)
        self._tracer = tracer

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        span_name = f"{request.method} {request.url.path}"
        with self._tracer.start_as_current_span(span_name) as span:
            trace_id = format(span.get_span_context().trace_id, "032x")
            # Stored on scope["state"], not the Request object, so it's visible
            # to route handlers even if BaseHTTPMiddleware runs call_next in a
            # separate task (contextvars would not propagate there; this does).
            request.state.trace_id = trace_id
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.route", request.url.path)
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
            response.headers["X-Trace-Id"] = trace_id
            return response
