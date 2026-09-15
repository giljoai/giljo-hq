# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import platform
from typing import Type

from .base import PlatformHandler
from .linux import LinuxPlatformHandler
from .macos import MacOSPlatformHandler
from .windows import WindowsPlatformHandler

_PLATFORM_HANDLERS: dict[str, Type[PlatformHandler]] = {
    "Windows": WindowsPlatformHandler,
    "Linux": LinuxPlatformHandler,
    "Darwin": MacOSPlatformHandler,
}


def get_platform_handler() -> PlatformHandler:
    system = platform.system()

    handler_class = _PLATFORM_HANDLERS.get(system)

    if handler_class is None:
        supported = ", ".join(_PLATFORM_HANDLERS.keys())
        raise RuntimeError(f"Unsupported platform: {system}. Supported platforms: {supported}")

    return handler_class()


__all__ = [
    "PlatformHandler",
    "WindowsPlatformHandler",
    "LinuxPlatformHandler",
    "MacOSPlatformHandler",
    "get_platform_handler",
]
