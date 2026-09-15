# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "mcp-registry" / "server.json"
VERSION_FILE = REPO_ROOT / "VERSION"


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_exists():
    assert MANIFEST.is_file(), "mcp-registry/server.json is missing"


def test_manifest_version_matches_version_file():
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    assert _manifest()["version"] == version, (
        f"mcp-registry/server.json version {_manifest()['version']!r} has "
        f"drifted from VERSION {version!r}; update the manifest"
    )


def test_registry_name_is_permanent():
    assert _manifest()["name"] == "ai.giljo/hq"


def test_remote_url_is_plain_mcp_endpoint():
    remotes = _manifest()["remotes"]
    assert len(remotes) == 1
    assert remotes[0]["type"] == "streamable-http"
    assert remotes[0]["url"] == "https://app.giljo.ai/mcp", (
        "The remote URL must stay the plain form. A URL carrying a query string "
        "does not match the resource identifier published in the "
        "protected-resource metadata, so RFC 9728 clients decline to register."
    )
    assert "?" not in remotes[0]["url"]
