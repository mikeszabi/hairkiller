from __future__ import annotations

from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send


class ApiPrefixMiddleware:
    """Allow the same FastAPI app to answer both `/...` and `/api/...` paths."""

    def __init__(self, app: ASGIApp, prefix: str = "/api") -> None:
        self.app = app
        self.prefix = prefix.rstrip("/") or "/api"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(f"{self.prefix}/"):
                rewritten = path[len(self.prefix):] or "/"
                scope = dict(scope)
                scope["path"] = rewritten

                raw_path = scope.get("raw_path")
                if raw_path:
                    prefix_bytes = self.prefix.encode("utf-8")
                    if raw_path == prefix_bytes or raw_path.startswith(prefix_bytes + b"/"):
                        scope["raw_path"] = raw_path[len(prefix_bytes):] or b"/"

        await self.app(scope, receive, send)


def install_api_prefix(app: FastAPI, prefix: str = "/api") -> None:
    app.add_middleware(ApiPrefixMiddleware, prefix=prefix)
