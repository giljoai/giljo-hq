# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
