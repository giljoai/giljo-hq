# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Annotated

from fastapi import Path, Query


ID_MAX = 64
THREAD_PROJECT_TAGS_MAX = 50
LIST_ITEMS_MAX = 10_000

IdPath = Annotated[str, Path(max_length=ID_MAX)]
IdQuery = Annotated[str | None, Query(max_length=ID_MAX)]
