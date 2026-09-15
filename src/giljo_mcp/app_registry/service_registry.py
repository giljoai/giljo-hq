# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any


_websocket_manager: Any | None = None


def set_websocket_manager(manager: Any) -> None:
    global _websocket_manager  # noqa: PLW0603
    _websocket_manager = manager


def get_websocket_manager() -> Any | None:
    return _websocket_manager
