# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from collections.abc import Callable


SLASH_COMMANDS: dict[str, Callable] = {}


def get_slash_command(command_name: str) -> Callable | None:
    return SLASH_COMMANDS.get(command_name)
