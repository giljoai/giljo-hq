# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app_state import GILJO_MODE
from giljo_mcp.auth.dependencies import get_db_session
from giljo_mcp.database import TenantIsolationError, tenant_isolation_bypass
from giljo_mcp.models import User


logger = logging.getLogger(__name__)

router = APIRouter()


_KNOWN_NON_CE_MODES = frozenset({"saas", "saas-production"})
_CE_MODE = "ce"


def _compute_setup_signal(
    *,
    mode: str,
    has_admin_user: bool,
    has_any_user: bool,
) -> dict[str, Any]:
    normalised = (mode or "").strip().lower()

    if normalised == _CE_MODE:
        is_fresh = not has_any_user
        return {
            "is_fresh_install": is_fresh,
            "requires_admin_creation": is_fresh,
            "show_public_landing": False,
            "route_signal": "create_admin" if is_fresh else "login",
        }

    _ = normalised in _KNOWN_NON_CE_MODES
    return {
        "is_fresh_install": False,
        "requires_admin_creation": False,
        "show_public_landing": True,
        "route_signal": "public_landing",
    }


@router.get("/status")
async def get_setup_security_status(db: AsyncSession = Depends(get_db_session)):
    """
    Setup-status detection driven by the policy table.

    Returns fields consumed by frontend router.beforeEach:
      * setup_complete
      * is_fresh_install         (CE-only semantic)
      * requires_admin_creation  (CE-only semantic)
      * show_public_landing      (saas flag, used by router guard)
      * route_signal             ('create_admin' | 'login' | 'public_landing')
      * total_users_count        (int)
      * mode                     (echoed for frontend debugging)
      * sentryDsn                (camelCase; SENTRY_DSN_FRONTEND in saas, else null)
      * environment              (camelCase; echoes GILJO_MODE, defaulting to 'ce')
    """
    try:
        total_users_stmt = select(func.count(User.id))
        admin_users_stmt = select(func.count(User.id)).where(User.role == "admin")

        with tenant_isolation_bypass(
            db,
            reason="pre-auth system-wide setup-state user count precedes tenant resolution",
            models=(User,),
        ):
            total_users_count = (await db.execute(total_users_stmt)).scalar() or 0
            admin_users_count = (await db.execute(admin_users_stmt)).scalar() or 0

        signal = _compute_setup_signal(
            mode=GILJO_MODE,
            has_admin_user=admin_users_count > 0,
            has_any_user=total_users_count > 0,
        )

        if signal["is_fresh_install"]:
            logger.info("[SETUP] Fresh install detected (mode=ce, 0 users). Create-admin flow active.")
        else:
            logger.debug(
                "[SETUP] mode=%s total_users=%d admins=%d route_signal=%s",
                GILJO_MODE,
                total_users_count,
                admin_users_count,
                signal["route_signal"],
            )

        return {
            "setup_complete": not signal["is_fresh_install"],
            "is_fresh_install": signal["is_fresh_install"],
            "requires_admin_creation": signal["requires_admin_creation"],
            "show_public_landing": signal["show_public_landing"],
            "route_signal": signal["route_signal"],
            "total_users_count": min(total_users_count, 1) if GILJO_MODE == "saas" else total_users_count,
            "mode": GILJO_MODE,
            "sentryDsn": _resolve_sentry_dsn(GILJO_MODE),
            "environment": _resolve_environment(GILJO_MODE),
        }

    except (ValueError, KeyError, TenantIsolationError):
        logger.exception("Failed to get setup status")
        return {
            "setup_complete": False,
            "is_fresh_install": False,
            "requires_admin_creation": False,
            "show_public_landing": True,
            "route_signal": "public_landing",
            "mode": GILJO_MODE,
            "sentryDsn": _resolve_sentry_dsn(GILJO_MODE),
            "environment": _resolve_environment(GILJO_MODE),
        }


def _resolve_sentry_dsn(mode: str) -> str | None:
    if (mode or "").strip().lower() == "saas":
        return os.environ.get("SENTRY_DSN_FRONTEND") or None
    return None


def _resolve_environment(mode: str) -> str:
    return (mode or "").strip().lower() or "ce"
