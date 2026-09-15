# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

import importlib


def test_giljo_mcp_validation_imports_without_error() -> None:
    module = importlib.import_module("giljo_mcp.validation")
    assert module.TemplateValidator is not None
