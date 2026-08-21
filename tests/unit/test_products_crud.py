# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Unit tests for products CRUD response building - Handover 0126.

BE-5118 regression guard: _build_product_response must surface the AI-owned
vision-analysis fields end-to-end.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock


class TestBuildProductResponseVisionAnalysisFields:
    """BE-5118 regression: ProductResponse must surface the AI-owned vision-analysis
    state (vision_analysis_complete + consolidated_vision_*) end-to-end.

    The frontend unlock gate (BE-5118) reads these fields off the strict pydantic
    response model. BE-5117 added them to the ORM/DB layer but did not wire them
    through _build_product_response, so the API silently dropped them and the gate
    was non-functional. This test locks the mapping in at the failing layer.
    """

    def _make_product(self, **overrides):
        product = MagicMock()
        product.id = "prod-be5118"
        product.name = "BE-5118 fixture"
        # BE-9385b: ProductResponse now carries the export slug, and a bare MagicMock
        # attribute is not a string Pydantic will accept. None is the honest value --
        # a row predating ce_0092 has no slug and the render path derives one.
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
        """Newly-created products may have vision_analysis_complete=NULL until the
        DB default lands. The response layer must coerce to a strict bool so the
        frontend gate has a defined value."""
        from api.endpoints.products.crud import _build_product_response

        response = _build_product_response(self._make_product(vision_analysis_complete=None))

        assert response.vision_analysis_complete is False


class TestBuildProductResponseMemoryDefault:
    """BE-9261: the product_memory None-fallback seeds the renamed git_integration
    key, not the legacy github key."""

    def _make_product(self, **overrides):
        product = MagicMock()
        product.id = "prod-be9261"
        product.name = "BE-9261 fixture"
        # BE-9385b: see the note above -- ProductResponse validates slug as str|None.
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
