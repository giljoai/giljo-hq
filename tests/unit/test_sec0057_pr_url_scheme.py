# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from pydantic import ValidationError

from giljo_mcp.schemas.jsonb_validators import validate_agent_execution_result


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(document.cookie)",
        " JavaScript:alert(1)",
        "java\tscript:alert(1)",
        "data:text/html,<b>hi</b>",
        "vbscript:msgbox",
        "file:///etc/passwd",
        "//evil.example/pr/1",
        "https://",
        "not a url",
    ],
)
def test_pr_url_with_a_non_web_scheme_is_refused(url):
    with pytest.raises(ValidationError) as exc:
        validate_agent_execution_result({"summary": "done", "pr_url": url})
    assert exc.value.errors()[0]["loc"] == ("pr_url",)


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "   ",
        "https://git.example/o/r/pulls/9",
        "http://198.51.100.7:3000/o/r/pulls/1",
        "HTTPS://Git.Example/x",
    ],
)
def test_pr_url_web_or_blank_is_accepted_unchanged(url):
    payload = {"summary": "done", "pr_url": url, "files_changed": ["a.py"]}
    assert validate_agent_execution_result(payload) is payload
