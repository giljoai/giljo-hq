# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from fastapi import FastAPI


logger = logging.getLogger("api.app")


async def run_saas_oauth_hydration(app: FastAPI) -> None:
    hydrate = getattr(app.state, "saas_oauth_hydrate", None)
    if hydrate is None:
        return
    try:
        await hydrate()
    except Exception:  # noqa: BLE001 -- best-effort boot phase; a DB-less boot must still start
        logger.warning(
            "oauth_clients cache hydration failed — the resolver is installed and will "
            "populate lazily via DCR + miss-lookup; the readiness line is absent this boot",
            exc_info=True,
        )
