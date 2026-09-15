# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from collections.abc import Collection
from typing import Any


def split_known(supplied: dict[str, Any], known: Collection[str]) -> tuple[dict[str, Any], list[str]]:
    used = {key: value for key, value in supplied.items() if key in known}
    unknown = sorted(key for key in supplied if key not in known)
    return used, unknown
