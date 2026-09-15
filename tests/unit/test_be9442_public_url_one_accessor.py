# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import os
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

SLASHED = "https://app.giljo.ai/"
UNSLASHED = "https://app.giljo.ai"
CE_DEFAULT = "http://localhost:7272"


def _thin_prompt(**overrides) -> str:
    from giljo_mcp.prompts.staging_prompt_builder import StagingPromptBuilder

    project = MagicMock()
    project.id = "proj-abc"
    project.name = "Test Project"
    project.description = "Test desc"
    project.mission = ""
    project.taxonomy_alias = None
    project.project_type_id = None
    project.series_number = None
    product = MagicMock()
    product.id = "prod-xyz"

    kwargs = {
        "orchestrator_id": "orch-1",
        "agent_id": "agent-1",
        "project_id": "proj-abc",
        "project": project,
        "product": product,
        "tool": "claude-code",
        "field_toggles": {},
        "depth_config": {},
        "user_id": None,
    }
    kwargs.update(overrides)
    return StagingPromptBuilder().build_thin_prompt(**kwargs)


class TestRenderedStagingPrompt:

    def test_rendered_prompt_has_no_double_slash_health(self, monkeypatch):
        monkeypatch.setenv("GILJO_PUBLIC_URL", SLASHED)
        prompt = _thin_prompt()
        assert "//health" not in prompt, (
            "BE-9442: rendered staging prompt contains a malformed '//health' URL. "
            "GILJO_PUBLIC_URL was set with a trailing slash and reached the prompt "
            "un-normalised."
        )

    def test_rendered_prompt_interpolates_unslashed_url_everywhere(self, monkeypatch):
        monkeypatch.setenv("GILJO_PUBLIC_URL", SLASHED)
        prompt = _thin_prompt()
        assert f"- Server URL: {UNSLASHED}\n" in prompt
        assert f"Check server running at {UNSLASHED}/health" in prompt
        assert f"{UNSLASHED}//" not in prompt

    def test_rendered_prompt_unaffected_when_value_already_clean(self, monkeypatch):
        monkeypatch.setenv("GILJO_PUBLIC_URL", UNSLASHED)
        prompt = _thin_prompt()
        assert f"Check server running at {UNSLASHED}/health" in prompt
        assert "//health" not in prompt

    def test_rendered_prompt_default_is_ce_localhost(self, monkeypatch):
        monkeypatch.delenv("GILJO_PUBLIC_URL", raising=False)
        prompt = _thin_prompt()
        assert f"- Server URL: {CE_DEFAULT}\n" in prompt
        assert f"Check server running at {CE_DEFAULT}/health" in prompt


class TestReadersNormalise:

    def _site_1_conductor(self) -> str:
        from api.endpoints.prompts import _conductor_mcp_url

        return _conductor_mcp_url()

    def _site_2_staging_builder(self) -> str:
        prompt = _thin_prompt()
        match = re.search(r"^- Server URL: (.+)$", prompt, re.MULTILINE)
        assert match, "staging prompt no longer renders a '- Server URL:' line"
        return match.group(1)

    def _site_3_continuation(self) -> str:
        from giljo_mcp.thin_prompt_generator import build_continuation_prompt

        prompt = build_continuation_prompt(
            project_id="proj-abc",
            agent_id="agent-1",
            job_id="job-1",
        )
        match = re.search(r"(https?://\S+?)/mcp\b", prompt)
        assert match, "continuation prompt no longer renders an MCP URL"
        return match.group(1)

    def _site_4_generator_method(self) -> str:
        from giljo_mcp.thin_prompt_generator import ThinClientPromptGenerator

        return ThinClientPromptGenerator._get_public_base_url(MagicMock())

    ALL_SITES = {
        "site1_prompts_conductor_mcp_url": _site_1_conductor,
        "site2_staging_prompt_builder": _site_2_staging_builder,
        "site3_build_continuation_prompt": _site_3_continuation,
        "site4_thin_generator_get_public_base_url": _site_4_generator_method,
    }

    @pytest.mark.parametrize("site_name", sorted(ALL_SITES))
    def test_reader_strips_trailing_slash(self, site_name, monkeypatch):
        monkeypatch.setenv("GILJO_PUBLIC_URL", SLASHED)
        value = self.ALL_SITES[site_name](self)
        assert value == UNSLASHED, (
            f"BE-9442: {site_name} returned {value!r} for GILJO_PUBLIC_URL={SLASHED!r}. "
            f"Every reader must normalise identically."
        )

    @pytest.mark.parametrize("site_name", sorted(ALL_SITES))
    def test_reader_default_preserved(self, site_name, monkeypatch):
        monkeypatch.delenv("GILJO_PUBLIC_URL", raising=False)
        assert self.ALL_SITES[site_name](self) == CE_DEFAULT


class TestBootstrapSetupDownloadUrl:

    async def _bootstrap(self, monkeypatch) -> dict:
        import giljo_mcp.downloads.token_manager as token_manager_mod
        import giljo_mcp.file_staging as file_staging_mod
        import giljo_mcp.services.product_service as product_service_mod
        from giljo_mcp.tools.tool_accessor._setup_tools import SetupMiscMixin

        class _FakeProductService:

            def __init__(self, *args, **kwargs):
                pass

            async def list_products(self, include_inactive=False, lean=False):
                return []

        monkeypatch.setattr(product_service_mod, "ProductService", _FakeProductService)

        class _FakeTokenManager:
            def __init__(self, db_session=None):
                pass

            async def generate_token(self, **kwargs):
                return "TOKEN123"

            async def mark_ready(self, token):
                return None

            async def mark_failed(self, token, message):  # pragma: no cover - not hit
                return None

        class _FakeStaging:
            def __init__(self, db_session=None):
                pass

            async def create_staging_directory(self, tenant_key, token):
                return "/tmp/staging"

            async def stage_setup_bundle(self, *args, **kwargs):
                return ("/tmp/staging/giljo_setup.zip", "ok")

        monkeypatch.setattr(token_manager_mod, "TokenManager", _FakeTokenManager)
        monkeypatch.setattr(file_staging_mod, "FileStaging", _FakeStaging)

        class _FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        class _Accessor(SetupMiscMixin):
            db_manager = None

            def get_session_async(self):
                return _FakeSession()

        return await _Accessor().bootstrap_setup(tenant_key="t-1", platform="claude_code")

    async def test_download_url_has_no_double_slash(self, monkeypatch):
        monkeypatch.setenv("GILJO_PUBLIC_URL", SLASHED)
        result = await self._bootstrap(monkeypatch)
        rendered = str(result)
        assert f"{UNSLASHED}/api/download/temp/TOKEN123/giljo_setup.zip" in rendered
        assert "//api/download" not in rendered

    async def test_download_url_default_preserved(self, monkeypatch):
        monkeypatch.delenv("GILJO_PUBLIC_URL", raising=False)
        result = await self._bootstrap(monkeypatch)
        assert f"{CE_DEFAULT}/api/download/temp/TOKEN123/giljo_setup.zip" in str(result)


class TestAccessorContract:

    def test_strips_trailing_slash(self, monkeypatch):
        from giljo_mcp.http.url_resolver import get_public_url

        monkeypatch.setenv("GILJO_PUBLIC_URL", SLASHED)
        assert get_public_url() == UNSLASHED

    def test_strips_repeated_slashes_and_surrounding_whitespace(self, monkeypatch):
        from giljo_mcp.http.url_resolver import get_public_url

        monkeypatch.setenv("GILJO_PUBLIC_URL", "  https://app.giljo.ai//  ")
        assert get_public_url() == UNSLASHED

    def test_unset_returns_ce_default(self, monkeypatch):
        from giljo_mcp.http.url_resolver import get_public_url

        monkeypatch.delenv("GILJO_PUBLIC_URL", raising=False)
        assert get_public_url() == CE_DEFAULT

    def test_set_but_empty_returns_ce_default(self, monkeypatch):
        from giljo_mcp.http.url_resolver import get_public_url

        monkeypatch.setenv("GILJO_PUBLIC_URL", "")
        assert get_public_url() == CE_DEFAULT

    def test_public_base_url_is_untouched(self, monkeypatch):
        from giljo_mcp.http import url_resolver

        monkeypatch.setenv("GILJO_PUBLIC_BASE_URL", "https://pinned.example.com")
        monkeypatch.setenv("GILJO_PUBLIC_URL", SLASHED)
        assert url_resolver.get_public_url() == UNSLASHED


class TestNoDirectReadsSurvive:

    SCAN_ROOTS = ("src", "api")
    ACCESSOR_FILE = Path("src") / "giljo_mcp" / "http" / "url_resolver.py"
    PATTERN = re.compile(r"os\.(environ|getenv)\b.*GILJO_PUBLIC_URL")

    def test_no_direct_env_reads_outside_the_accessor(self):
        offenders = []
        for root in self.SCAN_ROOTS:
            for path in (REPO_ROOT / root).rglob("*.py"):
                rel = path.relative_to(REPO_ROOT)
                if rel == self.ACCESSOR_FILE:
                    continue
                for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                    if self.PATTERN.search(line):
                        offenders.append(f"{rel.as_posix()}:{lineno}: {line.strip()}")

        assert not offenders, (
            "BE-9442 DoD 2: GILJO_PUBLIC_URL must be read only through "
            "giljo_mcp.http.url_resolver.get_public_url(). Direct reads still present:\n  " + "\n  ".join(offenders)
        )

    def test_scanner_actually_matches_the_shapes_it_claims_to(self):
        assert self.PATTERN.search('x = os.environ.get("GILJO_PUBLIC_URL", "http://localhost:7272")')
        assert self.PATTERN.search('x = (os.environ.get("GILJO_PUBLIC_URL") or "d").rstrip("/")')
        assert self.PATTERN.search('x = os.getenv("GILJO_PUBLIC_URL")')
        assert not self.PATTERN.search("# Fall back to GILJO_PUBLIC_URL env var")
        assert not self.PATTERN.search('"""Reads MCP URL from GILJO_PUBLIC_URL env-var."""')

    def test_scan_roots_exist(self):
        for root in self.SCAN_ROOTS:
            assert (REPO_ROOT / root).is_dir(), f"scan root {root} missing"
        assert (REPO_ROOT / self.ACCESSOR_FILE).is_file()
        assert os.environ is not None
