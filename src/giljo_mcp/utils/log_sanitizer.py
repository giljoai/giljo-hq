# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import re


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize(value: str) -> str:
    text = value if isinstance(value, str) else str(value)
    text = text.replace("\r\n", "").replace("\r", "").replace("\n", "")
    return _CONTROL_CHARS.sub("", text)


def mask_token(token: str) -> str:
    if not isinstance(token, str):
        token = str(token)
    if len(token) > 8:
        token = token[:8] + "..."
    return sanitize(token)
