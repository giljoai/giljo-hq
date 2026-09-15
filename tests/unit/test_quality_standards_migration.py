# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from sqlalchemy import Text

from giljo_mcp.models.products import Product


def test_quality_standards_field_exists():
    assert hasattr(Product, "quality_standards"), "Product model should have quality_standards field"


def test_quality_standards_nullable():
    column = Product.__table__.columns.get("quality_standards")
    assert column is not None, "quality_standards column should exist in Product table"
    assert column.nullable is True, "quality_standards column should be nullable"


def test_quality_standards_is_text_type():
    column = Product.__table__.columns.get("quality_standards")
    assert column is not None, "quality_standards column should exist in Product table"
    assert isinstance(column.type, Text), "quality_standards column should be Text type"


def test_quality_standards_comment():
    column = Product.__table__.columns.get("quality_standards")
    assert column is not None, "quality_standards column should exist in Product table"
    assert column.comment is not None, "quality_standards column should have a comment"
    assert "quality standards" in column.comment.lower(), "Comment should describe quality standards purpose"
