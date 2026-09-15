# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest

from giljo_mcp.services.product_field_map import (
    RELATION_BLOCK_FIELDS,
    assemble_update_kwargs,
    block_for_column,
)




class TestBlockForColumn:
    def test_direct_columns_route_to_products(self):
        for col in ("name", "description", "core_features", "brand_guidelines", "target_platforms"):
            assert block_for_column(col) == "products"

    def test_relation_columns_route_to_their_block(self):
        assert block_for_column("backend_frameworks") == "tech_stack"
        assert block_for_column("primary_pattern") == "architecture"
        assert block_for_column("quality_standards") == "test_config"

    def test_unknown_column_returns_none(self):
        assert block_for_column("not_a_real_column") is None

    def test_every_column_resolves_to_a_block(self):
        for block, columns in RELATION_BLOCK_FIELDS.items():
            for col in columns:
                assert block_for_column(col) == block


class TestAssembleUpdateKwargs:
    def test_direct_columns_stay_top_level(self):
        kwargs = assemble_update_kwargs({"name": "X", "description": "Y"})
        assert kwargs == {"name": "X", "description": "Y"}

    def test_relation_columns_group_into_block(self):
        kwargs = assemble_update_kwargs({"backend_frameworks": "FastAPI"})
        assert kwargs == {"tech_stack": {"backend_frameworks": "FastAPI"}}

    def test_multiple_columns_same_block_accumulate(self):
        kwargs = assemble_update_kwargs({"backend_frameworks": "FastAPI", "databases_storage": "PostgreSQL"})
        assert kwargs == {"tech_stack": {"backend_frameworks": "FastAPI", "databases_storage": "PostgreSQL"}}

    def test_mixed_direct_and_relations(self):
        kwargs = assemble_update_kwargs(
            {
                "description": "An app",
                "api_style": "REST",
                "quality_standards": "90% coverage",
            }
        )
        assert kwargs == {
            "description": "An app",
            "architecture": {"api_style": "REST"},
            "test_config": {"quality_standards": "90% coverage"},
        }

    def test_unknown_columns_dropped(self):
        kwargs = assemble_update_kwargs({"bogus": "x", "name": "keep"})
        assert kwargs == {"name": "keep"}




class TestBothInputShapesConverge:

    def test_vision_extraction_shape(self):
        from giljo_mcp.tools.vision_analysis import _build_update_kwargs

        fields = {
            "product_description": "An AI app",
            "backend_frameworks": "FastAPI",
            "databases": "PostgreSQL",
            "api_style": "REST",
            "testing_strategy": "TDD",
        }
        fields_written: list[str] = []
        kwargs = _build_update_kwargs(fields, fields_written)

        assert kwargs == {
            "description": "An AI app",
            "tech_stack": {"backend_frameworks": "FastAPI", "databases_storage": "PostgreSQL"},
            "architecture": {"api_style": "REST"},
            "test_config": {"test_strategy": "TDD"},
        }
        assert set(fields_written) == {
            "product_description",
            "backend_frameworks",
            "databases",
            "api_style",
            "testing_strategy",
        }

    def test_tuning_section_shape(self):
        from giljo_mcp.services.product_tuning_service import ProductTuningService

        service = ProductTuningService.__new__(ProductTuningService)
        proposals = [
            {"section": "description", "drift_detected": True, "proposed_value": "An AI app"},
            {"section": "tech_stack.backend_frameworks", "drift_detected": True, "proposed_value": "FastAPI"},
            {"section": "tech_stack.databases_storage", "drift_detected": True, "proposed_value": "PostgreSQL"},
            {"section": "architecture.api_style", "drift_detected": True, "proposed_value": "REST"},
        ]
        kwargs, sections = service._build_update_kwargs(proposals)

        assert kwargs == {
            "description": "An AI app",
            "tech_stack": {"backend_frameworks": "FastAPI", "databases_storage": "PostgreSQL"},
            "architecture": {"api_style": "REST"},
        }
        assert set(sections) == {
            "description",
            "tech_stack.backend_frameworks",
            "tech_stack.databases_storage",
            "architecture.api_style",
        }

    def test_relation_block_dicts_are_structurally_identical(self):
        from giljo_mcp.services.product_tuning_service import ProductTuningService
        from giljo_mcp.tools.vision_analysis import _build_update_kwargs

        vision_kwargs = _build_update_kwargs({"backend_frameworks": "FastAPI", "databases": "PostgreSQL"}, [])

        service = ProductTuningService.__new__(ProductTuningService)
        tuning_kwargs, _ = service._build_update_kwargs(
            [
                {"section": "tech_stack.backend_frameworks", "drift_detected": True, "proposed_value": "FastAPI"},
                {"section": "tech_stack.databases_storage", "drift_detected": True, "proposed_value": "PostgreSQL"},
            ]
        )

        assert vision_kwargs["tech_stack"] == tuning_kwargs["tech_stack"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
