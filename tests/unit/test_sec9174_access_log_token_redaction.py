# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

import pytest

from giljo_mcp.logging import _SensitiveQueryAccessFilter, configure_logging


UVICORN_ACCESS_FORMAT = '%s - "%s %s HTTP/%s" %d'


def _access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg=UVICORN_ACCESS_FORMAT,
        args=("127.0.0.1:50000", "GET", path, "1.1", 200),
        exc_info=None,
    )


class TestSensitiveQueryAccessFilter:
    def test_reset_link_token_value_redacted(self):
        record = _access_record("/reset-password?token=plaintext-reset-secret")
        keep = _SensitiveQueryAccessFilter().filter(record)
        line = record.getMessage()
        assert keep is True, "redaction must never DROP the access line"
        assert "plaintext-reset-secret" not in line
        assert '"GET /reset-password?token=[REDACTED] HTTP/1.1" 200' in line

    def test_oauth_callback_code_and_state_redacted(self):
        record = _access_record("/api/auth/social/callback?code=oauth-code-secret&state=csrf-state-val")
        _SensitiveQueryAccessFilter().filter(record)
        line = record.getMessage()
        assert "oauth-code-secret" not in line
        assert "csrf-state-val" not in line
        assert "code=[REDACTED]&state=[REDACTED]" in line

    def test_sensitive_param_mixed_with_benign_params(self):
        record = _access_record("/confirm?email=a@b.example&token=tok-secret&page=2")
        _SensitiveQueryAccessFilter().filter(record)
        line = record.getMessage()
        assert "tok-secret" not in line
        assert "email=a@b.example" in line
        assert "page=2" in line

    def test_param_name_match_is_exact_not_substring(self):
        record = _access_record("/search?statement=select&csrftoken_like=keepme")
        _SensitiveQueryAccessFilter().filter(record)
        line = record.getMessage()
        assert "statement=select" in line
        assert "csrftoken_like=keepme" in line

    def test_benign_query_untouched(self):
        record = _access_record("/api/projects?page=2&sort=name")
        keep = _SensitiveQueryAccessFilter().filter(record)
        assert keep is True
        assert "/api/projects?page=2&sort=name" in record.getMessage()

    def test_path_without_query_untouched(self):
        record = _access_record("/api/health")
        keep = _SensitiveQueryAccessFilter().filter(record)
        assert keep is True
        assert '"GET /api/health HTTP/1.1" 200' in record.getMessage()

    def test_non_access_shaped_record_passes_through(self):
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="plain message, no args",
            args=None,
            exc_info=None,
        )
        assert _SensitiveQueryAccessFilter().filter(record) is True
        assert record.getMessage() == "plain message, no args"


class TestDownloadTokenPathSegmentRedacted:

    def test_download_token_path_segment_masked(self):
        record = _access_record("/api/download/temp/a1b2c3d4-e5f6-7890-abcd-ef1234567890/slash_commands.zip")
        keep = _SensitiveQueryAccessFilter().filter(record)
        line = record.getMessage()
        assert keep is True, "redaction must never DROP the access line"
        assert "a1b2c3d4-e5f6-7890-abcd-ef1234567890" not in line
        assert '"GET /api/download/temp/[REDACTED]/slash_commands.zip HTTP/1.1" 200' in line

    def test_download_token_path_segment_masked_with_trailing_query(self):
        record = _access_record("/api/download/temp/live-token-value/file.zip?debug=1")
        _SensitiveQueryAccessFilter().filter(record)
        line = record.getMessage()
        assert "live-token-value" not in line
        assert "/api/download/temp/[REDACTED]/file.zip?debug=1" in line

    def test_unrelated_download_path_untouched(self):
        record = _access_record("/api/downloads/temporary/report.csv")
        keep = _SensitiveQueryAccessFilter().filter(record)
        assert keep is True
        assert "/api/downloads/temporary/report.csv" in record.getMessage()

    @pytest.mark.asyncio
    async def test_end_to_end_download_request_line_has_no_token_value(self, caplog):
        configure_logging()
        logger = logging.getLogger("uvicorn.access")
        with caplog.at_level(logging.INFO, logger="uvicorn.access"):
            logger.info(
                UVICORN_ACCESS_FORMAT,
                "198.51.100.9:44100",
                "GET",
                "/api/download/temp/9f8e7d6c-5b4a-3210-fedc-ba9876543210/giljo_setup.zip",
                "1.1",
                200,
            )
        assert "9f8e7d6c-5b4a-3210-fedc-ba9876543210" not in caplog.text
        assert "/api/download/temp/[REDACTED]/giljo_setup.zip" in caplog.text


class TestFilterRegisteredOnUvicornAccess:
    def test_configure_logging_attaches_redaction_filter(self):
        configure_logging()
        access_logger = logging.getLogger("uvicorn.access")
        assert any(isinstance(f, _SensitiveQueryAccessFilter) for f in access_logger.filters)

    @pytest.mark.asyncio
    async def test_end_to_end_reset_request_line_has_no_token_value(self, caplog):
        configure_logging()
        logger = logging.getLogger("uvicorn.access")
        with caplog.at_level(logging.INFO, logger="uvicorn.access"):
            logger.info(
                UVICORN_ACCESS_FORMAT,
                "198.51.100.9:44100",
                "GET",
                "/reset-password?token=live-plaintext-token",
                "1.1",
                200,
            )
        assert "live-plaintext-token" not in caplog.text
        assert "token=[REDACTED]" in caplog.text
