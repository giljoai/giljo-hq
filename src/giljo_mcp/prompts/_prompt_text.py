# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from typing import Any


_BREAKS_AND_CONTROLS = re.compile(r"[\s\x00-\x1f\x7f-\x9f\u2028\u2029]+")
_DELIMITERS = str.maketrans({'"': "\u201d", "'": "\u2019", "`": "\u2019"})


def prompt_name(value: Any) -> str:
    if value is None:
        return ""
    return _BREAKS_AND_CONTROLS.sub(" ", str(value)).strip().translate(_DELIMITERS)
