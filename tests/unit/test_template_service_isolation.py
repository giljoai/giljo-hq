# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import AsyncMock, Mock

import pytest

from giljo_mcp.services.template_service import TemplateService
from tests.unit.conftest import make_mock_db_manager, make_mock_session


class TestTemplateServiceErrorHandling:

    @pytest.mark.asyncio
    async def test_get_template_database_exception(self):
        from giljo_mcp.exceptions import BaseGiljoError

        session = make_mock_session()
        session.__aenter__ = AsyncMock(side_effect=Exception("Connection lost"))
        db_manager = make_mock_db_manager(session)

        tenant_manager = Mock()
        tenant_manager.get_current_tenant = Mock(return_value="test-tenant")

        service = TemplateService(db_manager, tenant_manager)

        with pytest.raises(BaseGiljoError) as exc_info:
            await service.get_template(template_id="test-id")

        assert "Connection lost" in str(exc_info.value)
