# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations


def build_openapi_servers() -> list[dict[str, str]]:
    return [{"url": "/", "description": "This server"}]
