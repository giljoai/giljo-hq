# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from api.app_state import APIState


logger = logging.getLogger(__name__)


async def init_validation(state: APIState) -> None:
    if state.db_manager:
        try:
            logger.info("Checking setup state...")

            from giljo_mcp.setup.state_manager import SetupStateManager

            current_version = state.config.get_nested("installation.version", "2.0.0")
            db_version = "18"

            state_manager = SetupStateManager.get_instance(
                tenant_key="default",
                current_version=current_version,
                required_db_version=db_version,
            )

            if state_manager.requires_migration():
                logger.warning("Setup state version mismatch detected!")
                logger.warning(f"Current version: {current_version}")
                setup_state = state_manager.get_state()
                logger.warning(f"Stored version: {setup_state.get('setup_version')}")
                logger.warning("Run POST /api/setup/migrate to update state")
            else:
                logger.info("Setup state version is current")

            valid, failures = state_manager.validate_state()
            if not valid:
                logger.warning("Setup validation failures detected:")
                for failure in failures:
                    logger.warning(f"  - {failure}")
                logger.warning("Review setup configuration or run migration")
            else:
                logger.info("Setup state validation passed")

        except Exception:
            logger.exception("Optional startup phase [setup_validation] failed")
            state.degraded_services.append("setup_validation")
