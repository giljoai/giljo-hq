# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest
from pydantic import ValidationError


class TestDepthConfigFieldStandardization:

    def test_pydantic_model_uses_vision_documents(self):
        from api.endpoints.users import DepthConfig

        config = DepthConfig()
        assert hasattr(config, "vision_documents"), "DepthConfig must have 'vision_documents' field"
        assert not hasattr(config, "vision_chunking"), "DepthConfig must NOT have deprecated 'vision_chunking' field"
        assert config.vision_documents == "medium", "Default vision_documents should be 'medium'"

    def test_depth_config_accepts_all_levels(self):
        from api.endpoints.users import DepthConfig

        valid_levels = ["light", "medium", "full"]
        for level in valid_levels:
            config = DepthConfig(vision_documents=level)
            assert config.vision_documents == level, f"DepthConfig should accept '{level}' for vision_documents"

    def test_depth_config_rejects_invalid_levels(self):
        from api.endpoints.users import DepthConfig

        with pytest.raises(ValidationError):
            DepthConfig(vision_documents="invalid_level")

    def test_user_model_has_depth_vision_documents_column(self):
        from giljo_mcp.models.auth import User

        col = User.__table__.columns["depth_vision_documents"]
        assert col is not None, "User must have 'depth_vision_documents' column"
        assert col.server_default.arg == "medium", "Default depth_vision_documents should be 'medium'"

    def test_user_service_get_depth_config_uses_vision_documents(self):
        import inspect

        from giljo_mcp.services.user_service import UserService

        source = inspect.getsource(UserService._get_depth_config_impl)
        assert "vision_documents" in source or '"vision_documents"' in source, (
            "UserService._get_depth_config_impl must use 'vision_documents' in defaults"
        )
        assert "vision_chunking" not in source and '"vision_chunking"' not in source, (
            "UserService._get_depth_config_impl must NOT use deprecated 'vision_chunking'"
        )

    def test_user_service_validate_depth_config_checks_vision_documents(self):
        import inspect

        from giljo_mcp.services.user_service import UserService

        source = inspect.getsource(UserService._update_depth_config_impl)
        assert "vision_documents" in source or '"vision_documents"' in source, (
            "UserService validation must check 'vision_documents' field"
        )
        assert "vision_chunking" not in source and '"vision_chunking"' not in source, (
            "UserService validation must NOT check deprecated 'vision_chunking' field"
        )

    def test_project_service_uses_vision_documents(self):
        import inspect

        from giljo_mcp.services.project_launch_service import ProjectLaunchService

        source = inspect.getsource(ProjectLaunchService)

        assert "vision_documents" in source or '"vision_documents"' in source, (
            "ProjectLaunchService should reference 'vision_documents' field"
        )

        assert "vision_chunking" not in source and '"vision_chunking"' not in source, (
            "ProjectLaunchService should NOT reference deprecated 'vision_chunking' field"
        )

    def test_thin_prompt_generator_uses_vision_documents(self):
        import inspect

        from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator

        source = inspect.getsource(ThinClientPromptGenerator)

        assert "vision_documents" in source or '"vision_documents"' in source, (
            "ThinClientPromptGenerator should reference 'vision_documents' field"
        )

        assert "vision_chunking" not in source and '"vision_chunking"' not in source, (
            "ThinClientPromptGenerator should NOT reference deprecated 'vision_chunking' field"
        )


class TestFrontendFieldNaming:

    def test_frontend_component_uses_vision_documents(self):
        from pathlib import Path

        component_path = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "src"
            / "components"
            / "settings"
            / "ContextPriorityConfig.vue"
        )
        assert component_path.exists(), "ContextPriorityConfig.vue not found"

        content = component_path.read_text(encoding="utf-8")

        assert "vision_documents" in content or "vision_documents:" in content, (
            "ContextPriorityConfig.vue should use 'vision_documents' field"
        )

        assert "vision_document_depth" not in content, (
            "ContextPriorityConfig.vue should NOT use deprecated 'vision_document_depth' field"
        )
