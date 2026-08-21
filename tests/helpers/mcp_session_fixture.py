# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""The one place the test suite reaches the SDK's in-memory MCP transport.

Every MCP boundary and transport suite needs a ``ClientSession`` wired to our
MCP server instance over in-memory streams -- no TCP port, no auth middleware.
The MCP SDK used to ship exactly that as
``mcp.shared.memory.create_connected_server_and_client_session``, and 78 test
files call it.

**SDK 2.0 deleted that helper** (INF-9371). INF-9422 put this seam in front of it
precisely so the removal would be a one-file edit, and this is that edit: the
body below reconstructs the helper from the primitives 2.0 still ships, while the
exported name, the signature, and the yielded type are unchanged. No call site
moved.

What it is built from, and the one honest caveat:
  - ``create_client_server_memory_streams()`` (public, ``mcp.shared.memory``) --
    the stream pair the deleted helper was itself built on; only the wrapper went.
  - ``ClientSession`` (public, ``mcp.client``) -- so callers still get a
    ``ClientSession``, not 2.0's newer ``Client``, which lacks ``initialize``,
    ``initialize_result``, ``send_request`` and ``send_notification``.
  - ``server._lowlevel_server`` -- PRIVATE, and unavoidable: something has to run
    the server against those streams and ``MCPServer`` exposes no public accessor
    for its lowlevel server (the SDK carries its own TODO to make it public).
    This is not a new dependency on SDK internals: the deleted 1.x helper reached
    for exactly the same thing under the name ``server._mcp_server``.

Import it from here, never from ``mcp.shared.memory`` directly.
``test_inf9422_mcp_session_seam.py`` fails the suite if that rule is broken.

Edition Scope: Both (test-only helper).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import anyio
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams


__all__ = ["create_connected_server_and_client_session"]


@asynccontextmanager
async def create_connected_server_and_client_session(
    server: Any,
    read_timeout_seconds: timedelta | float | None = None,
    sampling_callback: Any = None,
    list_roots_callback: Any = None,
    logging_callback: Any = None,
    message_handler: Any = None,
    client_info: Any = None,
    raise_exceptions: bool = False,
) -> AsyncGenerator[ClientSession, None]:
    """Connect a client session to our MCP server over in-memory streams.

    Yields an initialized ``ClientSession``. Same call shapes the suite already
    uses: ``create_connected_server_and_client_session(mcp_sdk_server.mcp)`` and
    the ``client_info=`` variant.

    ``read_timeout_seconds`` keeps accepting a ``timedelta`` even though SDK 2.0's
    ``ClientSession`` now takes a float: absorbing that type change here is the
    reason the seam exists, so no call site has to care.
    """
    lowlevel = getattr(server, "_lowlevel_server", server)

    timeout = read_timeout_seconds
    if isinstance(timeout, timedelta):
        timeout = timeout.total_seconds()

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:

            async def run_server() -> None:
                await lowlevel.run(
                    server_read,
                    server_write,
                    lowlevel.create_initialization_options(),
                    raise_exceptions=raise_exceptions,
                )

            tg.start_soon(run_server)
            try:
                async with ClientSession(
                    read_stream=client_read,
                    write_stream=client_write,
                    read_timeout_seconds=timeout,
                    sampling_callback=sampling_callback,
                    list_roots_callback=list_roots_callback,
                    logging_callback=logging_callback,
                    message_handler=message_handler,
                    client_info=client_info,
                ) as client_session:
                    await client_session.initialize()
                    yield client_session
            finally:
                tg.cancel_scope.cancel()
