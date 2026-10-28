import json
import logging
from time import perf_counter
from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("legacy_rag.requests")


class SafeRequestMiddleware:
    """Log completion metadata and contain errors without logging request data."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        started_at = perf_counter()
        status_code = 503
        started = finished = False
        error_kind = None

        async def send_response(message: Message) -> None:
            nonlocal started, finished, status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                message = {**message, "headers": [*headers, (b"x-request-id", request_id.encode())]}
                started = True
            elif message["type"] == "http.response.body":
                finished = not message.get("more_body", False)
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        except Exception:  # noqa: BLE001 -- never pass raw dependency/route errors to server logs
            error_kind = "internal_error"
            if not started:
                response = JSONResponse({"detail": "service_unavailable"}, status_code=503)
                await response(scope, receive, send_response)
            elif not finished:
                # Headers already sent cannot be replaced; terminate the partial response safely.
                await send_response({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            method = scope.get("method", "")
            query_status = scope.get("state", {}).get("query_status")
            logger.info(json.dumps({
                "event": "request_complete", "request_id": request_id,
                "method": method if method in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"} else "OTHER",
                "route": getattr(scope.get("route"), "path", "unmatched"),
                "status_code": status_code,
                "elapsed_ms": round((perf_counter() - started_at) * 1000, 3),
                "error_kind": error_kind,
                "query_status": query_status if query_status in {"answered", "refused", "unavailable"} else None,
            }))
