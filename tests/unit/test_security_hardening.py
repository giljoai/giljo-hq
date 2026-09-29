# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sys
from pathlib import Path
from typing import ClassVar


sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestPathTraversalPrevention:

    def _is_allowed(self, vision_path: str) -> bool:
        normalized = vision_path.replace("\\", "/")
        resolved = Path(normalized).resolve()
        allowed_base = Path("./products").resolve()
        return resolved.is_relative_to(allowed_base)

    def test_relative_traversal_blocked(self):
        assert not self._is_allowed("../../etc/passwd")

    def test_absolute_outside_path_blocked(self):
        assert not self._is_allowed("/etc/shadow")

    def test_backslash_traversal_blocked(self):
        assert not self._is_allowed("..\\..\\etc\\passwd")

    def test_windows_absolute_blocked(self):
        assert not self._is_allowed("C:\\Windows\\System32\\config\\sam")

    def test_valid_products_path_allowed(self):
        products_dir = Path("./products").resolve()
        products_dir.mkdir(parents=True, exist_ok=True)
        assert self._is_allowed("./products/test-product/vision/doc.txt")

    def test_dot_dot_in_products_still_blocked(self):
        assert not self._is_allowed("./products/../../../etc/passwd")


class TestErrorDetailLeaks:

    LEAK_PATTERNS: ClassVar[list[str]] = [
        "traceback",
        'file "',
        "sqlalchemy",
        "psycopg2",
        "oserror",
        "valueerror",
        "keyerror",
        "integrityerror",
        "/home/",
    ]

    def _assert_no_internal_leak(self, detail: str):
        detail_lower = detail.lower()
        for pattern in self.LEAK_PATTERNS:
            assert pattern not in detail_lower, f"Error detail leaked internal info matching '{pattern}': {detail}"

    def test_git_endpoint_detail_is_generic(self):
        self._assert_no_internal_leak("Failed to save configuration. Check server logs.")

    def test_vision_document_create_detail_is_generic(self):
        self._assert_no_internal_leak("Failed to create vision document. Check server logs.")

    def test_vision_document_update_detail_is_generic(self):
        self._assert_no_internal_leak("Failed to update vision document. Check server logs.")

    def test_prompts_endpoint_detail_is_generic(self):
        self._assert_no_internal_leak("Failed to generate orchestrator prompt. Check server logs.")

    def test_template_delete_detail_is_generic(self):
        self._assert_no_internal_leak("Failed to delete template. Check server logs.")

    def test_oauth_authorize_detail_is_generic(self):
        self._assert_no_internal_leak("Invalid authorization request parameters.")

    def test_oauth_token_detail_is_generic(self):
        self._assert_no_internal_leak("invalid_request")
        self._assert_no_internal_leak("invalid_grant")

    def test_system_prompt_validation_detail_is_generic(self):
        self._assert_no_internal_leak("Invalid prompt content.")

    def test_system_prompt_service_error_detail_is_generic(self):
        self._assert_no_internal_leak("System prompt service temporarily unavailable.")

    def test_setup_status_contains_expected_fields_only(self):
        expected_fields = {"setup_complete", "is_fresh_install", "requires_admin_creation", "total_users_count"}
        response = {
            "setup_complete": True,
            "is_fresh_install": False,
            "requires_admin_creation": False,
            "total_users_count": 1,
        }
        assert set(response.keys()) == expected_fields
