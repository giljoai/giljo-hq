# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""OAuth client-cache hydration boot phase (BE-9580) — best-effort.

The SaaS OAuth resolver publishes a hydration coroutine on
``app.state.saas_oauth_hydrate`` when it installs (see
``giljo_mcp.saas.auth.oauth_resolver.install_saas_resolver``). This gate is the
lifespan's side of that handshake.

Why a handshake and not a direct call: the resolver installs during app
CONSTRUCTION (router wiring), but its DB session only exists after the lifespan
has run ``init_database``. Publishing a coroutine lets construction register the
work and the lifespan choose when to run it, without CE importing anything from
``saas/`` — CE simply finds no attribute and does nothing, so the Deletion Test
holds.

Policy is best-effort by design. Hydration is an optimisation plus one
observability line: the resolver is already installed and correct without it,
and the cache fills lazily via DCR ``cache_register`` and cache-miss lookups. A
setup-mode boot with no database must still start, which is what the original
hook did and what must stay true.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from fastapi import FastAPI


logger = logging.getLogger("api.app")


async def run_saas_oauth_hydration(app: FastAPI) -> None:
    """Await the OAuth client-cache hydration published by the SaaS resolver.

    No-op when nothing published one (CE, or a SaaS boot where the resolver
    failed to install — that failure is already logged at its own site).
    """
    hydrate = getattr(app.state, "saas_oauth_hydrate", None)
    if hydrate is None:
        return
    try:
        await hydrate()
    except Exception:  # noqa: BLE001 -- best-effort boot phase; a DB-less boot must still start
        # Best-effort by design: see the module docstring. The resolver is
        # installed and serving; only eager hydration and its readiness line
        # are lost, and the cache still fills lazily.
        logger.warning(
            "oauth_clients cache hydration failed — the resolver is installed and will "
            "populate lazily via DCR + miss-lookup; the readiness line is absent this boot",
            exc_info=True,
        )
