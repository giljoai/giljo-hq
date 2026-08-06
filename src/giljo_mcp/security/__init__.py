# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Security helper modules for Giljo HQ (Community Edition).

Subpackages:
    upload_guard: Filename sanitization and text-content byte-sniff for the
        vision document upload surface (SEC-0001 Phase 2).
"""

from .upload_guard import (
    TEXT_EXTENSIONS,
    UploadContentError,
    UploadFilenameError,
    UploadSizeError,
    enforce_text_content,
    is_text_content,
    sanitize_upload_filename,
)


__all__ = [
    "TEXT_EXTENSIONS",
    "UploadContentError",
    "UploadFilenameError",
    "UploadSizeError",
    "enforce_text_content",
    "is_text_content",
    "sanitize_upload_filename",
]
