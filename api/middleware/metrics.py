# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send


logger = logging.getLogger(__name__)


class APIMetricsMiddleware:

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        path = request.url.path
        if not (path == "/" or path.startswith("/assets/") or path == "/favicon.ico"):
            tenant_key = scope.get("state", {}).get("tenant_key")
            if tenant_key:
                request.app.state.api_state.api_call_count[tenant_key] = (
                    request.app.state.api_state.api_call_count.get(tenant_key, 0) + 1
                )

        await self.app(scope, receive, send)
