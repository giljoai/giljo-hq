# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from giljo_mcp import branding


def test_branding_constants_have_expected_values():
    assert branding.HOUSE_BRAND == "GiljoAI"
    assert branding.PRODUCT_NAME == "Giljo HQ"
    assert branding.PRODUCT_SHORT == "Giljo HQ"
    assert branding.MCP_ALIAS == "giljo_hq"
    assert branding.DESCRIPTOR == (
        "Giljo HQ — project, task, and agent coordination for the one-person software company"
    )


def test_two_hub_disambiguation_names_giljo_amh():
    assert "giljo_amh" in branding.TWO_HUB_DISAMBIGUATION
    assert "Giljo HQ" in branding.TWO_HUB_DISAMBIGUATION
