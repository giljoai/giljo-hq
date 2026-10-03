# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import re


_INTERNAL_ID = re.compile(r"Handovers? \d{3,4}|\b(?:BE|FE|SEC|INF|TSK|IMP|API|HO|SAAS)-\d{3,5}[a-z]?\b")
_TAXONOMY_EXAMPLE = "0001"


def internal_ids_in_openapi() -> list[str]:
    from api.app import create_app

    text = json.dumps(create_app().openapi())
    return [m.group(0) for m in _INTERNAL_ID.finditer(text) if _TAXONOMY_EXAMPLE not in m.group(0)]


def test_openapi_has_no_internal_ids():
    assert internal_ids_in_openapi() == []
