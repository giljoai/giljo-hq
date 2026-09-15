# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class McpDispatcher:

    def __init__(self, fastapi_app: ASGIApp, mcp_app: ASGIApp) -> None:
        self.fastapi_app = fastapi_app
        self.mcp_app = mcp_app

    def __getattr__(self, name: str):
        fastapi_app = self.__dict__.get("fastapi_app")
        if fastapi_app is None:
            raise AttributeError(name)
        return getattr(fastapi_app, name)

    @staticmethod
    def _is_mcp_path(path: str) -> bool:
        return path == "/mcp" or path.startswith("/mcp/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self._is_mcp_path(scope["path"]) and scope.get("method") != "OPTIONS":
            await self.mcp_app(scope, receive, send)
            return
        await self.fastapi_app(scope, receive, send)
