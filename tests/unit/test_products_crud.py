# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime
from unittest.mock import MagicMock


class TestBuildProductResponseVisionAnalysisFields:

    def _make_product(self, **overrides):
        product = MagicMock()
        product.id = "prod-be5118"
        product.name = "BE-5118 fixture"
        product.slug = None
        product.description = "fixture"
        product.project_path = "/tmp/be5118"
        now = datetime(2026, 5, 27, 12, 0, 0, tzinfo=UTC)
        product.created_at = now
        product.updated_at = now
        product.tech_stack = None
        product.architecture = None
        product.test_config = None
        product.product_memory = None
        product.core_features = ""
        product.brand_guidelines = None
        product.extraction_custom_instructions = None
        product.is_active = True
        product.target_platforms = ["all"]
        product.vision_analysis_complete = True
        product.consolidated_vision_light = "Light summary."
        product.consolidated_vision_medium = "Medium summary."
        product.consolidated_vision_light_tokens = 12
        product.consolidated_vision_medium_tokens = 34
        product.consolidated_vision_hash = "deadbeef"
        product.consolidated_at = None
        for key, value in overrides.items():
            setattr(product, key, value)
        return product

    def test_analyzed_product_surfaces_all_vision_fields(self):
        from api.endpoints.products.crud import _build_product_response

        response = _build_product_response(self._make_product())

        assert response.vision_analysis_complete is True
        assert response.consolidated_vision_light == "Light summary."
        assert response.consolidated_vision_medium == "Medium summary."
        assert response.consolidated_vision_light_tokens == 12
        assert response.consolidated_vision_medium_tokens == 34
        assert response.consolidated_vision_hash == "deadbeef"

    def test_pending_product_reports_gate_closed(self):
        from api.endpoints.products.crud import _build_product_response

        response = _build_product_response(
            self._make_product(
                vision_analysis_complete=False,
                consolidated_vision_light=None,
                consolidated_vision_medium=None,
                consolidated_vision_light_tokens=None,
                consolidated_vision_medium_tokens=None,
                consolidated_vision_hash=None,
            )
        )

        assert response.vision_analysis_complete is False
        assert response.consolidated_vision_light is None
        assert response.consolidated_vision_medium is None

    def test_null_flag_coerced_to_false(self):
        from api.endpoints.products.crud import _build_product_response

        response = _build_product_response(self._make_product(vision_analysis_complete=None))

        assert response.vision_analysis_complete is False


class TestBuildProductResponseMemoryDefault:

    def _make_product(self, **overrides):
        product = MagicMock()
        product.id = "prod-be9261"
        product.name = "BE-9261 fixture"
        product.slug = None
        product.description = "fixture"
        product.project_path = "/tmp/be9261"
        now = datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC)
        product.created_at = now
        product.updated_at = now
        product.tech_stack = None
        product.architecture = None
        product.test_config = None
        product.product_memory = None
        product.core_features = ""
        product.brand_guidelines = None
        product.extraction_custom_instructions = None
        product.is_active = True
        product.target_platforms = ["all"]
        product.vision_analysis_complete = True
        product.consolidated_vision_light = None
        product.consolidated_vision_medium = None
        product.consolidated_vision_light_tokens = None
        product.consolidated_vision_medium_tokens = None
        product.consolidated_vision_hash = None
        product.consolidated_at = None
        for key, value in overrides.items():
            setattr(product, key, value)
        return product

    def test_none_product_memory_defaults_to_git_integration_key(self):
        from api.endpoints.products.crud import _build_product_response

        response = _build_product_response(self._make_product(product_memory=None))

        assert response.product_memory["git_integration"] == {}
        assert "github" not in response.product_memory
