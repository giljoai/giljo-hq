# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.app_state import APIState


@pytest.mark.asyncio
async def test_init_database_sets_db_manager_on_state():
    from api.startup.database import init_database

    state = APIState()

    with (
        patch("api.startup.database.get_config") as mock_get_config,
        patch("api.startup.database.DatabaseManager") as mock_db_manager,
        patch.dict(os.environ, {"DATABASE_URL": "postgresql://localhost/test"}),
    ):
        mock_config = MagicMock()
        mock_get_config.return_value = mock_config

        mock_db_instance = MagicMock()
        mock_db_instance.create_tables_async = AsyncMock()
        mock_db_manager.return_value = mock_db_instance

        await init_database(state)

        assert state.db_manager is not None
        assert state.config is not None
        mock_db_instance.create_tables_async.assert_called_once()


@pytest.mark.asyncio
async def test_init_database_uses_env_url_first():
    from api.startup.database import init_database

    state = APIState()
    env_url = "postgresql://envuser:envpass@envhost/envdb"

    with (
        patch("api.startup.database.get_config") as mock_get_config,
        patch("api.startup.database.DatabaseManager") as mock_db_manager,
        patch.dict(os.environ, {"DATABASE_URL": env_url}),
    ):
        mock_config = MagicMock()
        mock_config.database.pg_pool_size = 10
        mock_config.database.pg_max_overflow = 10
        mock_config.database.pg_slot_budget = 90
        mock_get_config.return_value = mock_config

        mock_db_instance = MagicMock()
        mock_db_instance.create_tables_async = AsyncMock()
        mock_db_manager.return_value = mock_db_instance

        await init_database(state)

        mock_db_manager.assert_called_once_with(env_url, is_async=True, pool_size=10, max_overflow=10)


@pytest.mark.asyncio
async def test_init_database_uses_config_url_when_no_env():
    from api.startup.database import init_database

    state = APIState()
    config_url = "postgresql://configuser:configpass@confighost/configdb"

    with (
        patch("api.startup.database.get_config") as mock_get_config,
        patch("api.startup.database.DatabaseManager") as mock_db_manager,
        patch.dict(os.environ, {}, clear=True),
    ):
        mock_config = MagicMock()
        mock_config.database.get_connection_string.return_value = config_url
        mock_config.database.pg_pool_size = 10
        mock_config.database.pg_max_overflow = 10
        mock_config.database.pg_slot_budget = 90
        mock_get_config.return_value = mock_config

        mock_db_instance = MagicMock()
        mock_db_instance.create_tables_async = AsyncMock()
        mock_db_manager.return_value = mock_db_instance

        await init_database(state)

        mock_config.database.get_connection_string.assert_called_once()
        mock_db_manager.assert_called_once_with(config_url, is_async=True, pool_size=10, max_overflow=10)


@pytest.mark.asyncio
async def test_init_database_raises_on_missing_url():
    from api.startup.database import init_database

    state = APIState()

    with patch("api.startup.database.get_config") as mock_get_config, patch.dict(os.environ, {}, clear=True):
        mock_config = MagicMock()
        mock_config.database = None
        mock_get_config.return_value = mock_config

        with pytest.raises(ValueError, match="Database URL not configured"):
            await init_database(state)


@pytest.mark.asyncio
async def test_init_database_initializes_system_prompt_service():
    from api.startup.database import init_database

    state = APIState()

    with (
        patch("api.startup.database.get_config") as mock_get_config,
        patch("api.startup.database.DatabaseManager") as mock_db_manager,
        patch("api.startup.database.SystemPromptService") as mock_prompt_service,
        patch.dict(os.environ, {"DATABASE_URL": "postgresql://localhost/test"}),
    ):
        mock_config = MagicMock()
        mock_get_config.return_value = mock_config

        mock_db_instance = MagicMock()
        mock_db_instance.create_tables_async = AsyncMock()
        mock_db_manager.return_value = mock_db_instance

        await init_database(state)

        mock_prompt_service.assert_called_once_with(state.db_manager)
        assert state.system_prompt_service is not None


@pytest.mark.asyncio
async def test_init_database_skips_create_all_in_saas_mode(monkeypatch):
    from api.startup.database import init_database

    monkeypatch.setenv("GILJO_MODE", "saas")
    state = APIState()

    with (
        patch("api.startup.database.get_config") as mock_get_config,
        patch("api.startup.database.DatabaseManager") as mock_db_manager,
        patch.dict(os.environ, {"DATABASE_URL": "postgresql://localhost/test"}),
    ):
        monkeypatch.setenv("GILJO_MODE", "saas")
        mock_get_config.return_value = MagicMock()

        mock_db_instance = MagicMock()
        mock_db_instance.create_tables_async = AsyncMock()
        mock_db_manager.return_value = mock_db_instance

        await init_database(state)

        mock_db_instance.create_tables_async.assert_not_called()
        assert state.db_manager is not None


@pytest.mark.asyncio
async def test_init_database_calls_create_all_in_ce_mode(monkeypatch):
    from api.startup.database import init_database

    monkeypatch.setenv("GILJO_MODE", "")
    state = APIState()

    with (
        patch("api.startup.database.get_config") as mock_get_config,
        patch("api.startup.database.DatabaseManager") as mock_db_manager,
        patch.dict(os.environ, {"DATABASE_URL": "postgresql://localhost/test"}),
    ):
        monkeypatch.setenv("GILJO_MODE", "")
        mock_get_config.return_value = MagicMock()

        mock_db_instance = MagicMock()
        mock_db_instance.create_tables_async = AsyncMock()
        mock_db_manager.return_value = mock_db_instance

        await init_database(state)

        mock_db_instance.create_tables_async.assert_called_once()


@pytest.mark.asyncio
async def test_init_database_logs_connection_info():
    from api.startup.database import init_database

    state = APIState()
    db_url = "postgresql://user:password@localhost:5432/testdb"

    with (
        patch("api.startup.database.get_config") as mock_get_config,
        patch("api.startup.database.DatabaseManager") as mock_db_manager,
        patch("api.startup.database.logger") as mock_logger,
        patch.dict(os.environ, {"DATABASE_URL": db_url}),
    ):
        mock_config = MagicMock()
        mock_get_config.return_value = mock_config

        mock_db_instance = MagicMock()
        mock_db_instance.create_tables_async = AsyncMock()
        mock_db_manager.return_value = mock_db_instance

        await init_database(state)

        info_calls = [call.args[0] % call.args[1:] for call in mock_logger.info.call_args_list]
        assert any("localhost:5432/testdb" in msg for msg in info_calls)
        assert not any("password" in msg for msg in info_calls)
