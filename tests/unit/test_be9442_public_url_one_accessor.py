# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9442 — GILJO_PUBLIC_URL is read six ways and normalised three ways.

The defect: an operator sets ``GILJO_PUBLIC_URL=https://app.giljo.ai/`` — one
trailing slash, the natural way anyone pastes a URL — and the *same value* comes
out normalised on some code paths and raw on others. The observable symptom is
in the staging prompt every spawned orchestrator reads: line 162 of
``staging_prompt_builder`` renders ``Check server running at {mcp_url}/health``,
which becomes ``https://app.giljo.ai//health``.

The shape that makes this survive testing is that it is *inconsistent*, not
broken: whichever path a test exercises looks fine.

Test layering here, deliberately:

* ``TestRenderedStagingPrompt`` is the fail-first reproduction (DoD 4). It runs
  against the production render path and goes RED on its assertion — not on an
  import or a missing fixture — before the fix exists.
* ``TestReadersNormalise`` covers the individual readers. Sites 3 and 4 already
  normalised, so those cases pass on BOTH sides of the change; sites 1 and 2 go
  red before it. That asymmetry is the point.
* ``TestAccessorContract`` and ``TestNoDirectReadsSurvive`` describe the new
  surface and can only pass after it exists. They are NOT the fail-first
  evidence and should not be read as such.
"""

import os
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

# A trailing-slash value, exactly as an operator would paste it.
SLASHED = "https://app.giljo.ai/"
UNSLASHED = "https://app.giljo.ai"
CE_DEFAULT = "http://localhost:7272"


def _thin_prompt(**overrides) -> str:
    """Render the real staging spawn prompt (StagingPromptBuilder.build_thin_prompt).

    Mirrors the fixture shape in
    tests/services/test_ce_0033_orchestrator_discoverability.py — MagicMock
    project/product, no DB. Rendering the production output is the whole point:
    a unit test on the helper would not have caught this.
    """
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
    """DoD 4 — the observable symptom, asserted on what actually reaches the agent."""

    def test_rendered_prompt_has_no_double_slash_health(self, monkeypatch):
        """The reproduction. RED before the fix, on this assertion.

        staging_prompt_builder renders 'Check server running at {mcp_url}/health'.
        With an unnormalised mcp_url that is a malformed URL handed to every
        orchestrator spawned from this prompt.
        """
        monkeypatch.setenv("GILJO_PUBLIC_URL", SLASHED)
        prompt = _thin_prompt()
        assert "//health" not in prompt, (
            "BE-9442: rendered staging prompt contains a malformed '//health' URL. "
            "GILJO_PUBLIC_URL was set with a trailing slash and reached the prompt "
            "un-normalised."
        )

    def test_rendered_prompt_interpolates_unslashed_url_everywhere(self, monkeypatch):
        """mcp_url lands in three places (lines 113, 162, 222). None may double up.

        Asserting on '//health' alone would let the other two sites drift, so
        pin the value itself at every interpolation.
        """
        monkeypatch.setenv("GILJO_PUBLIC_URL", SLASHED)
        prompt = _thin_prompt()
        assert f"- Server URL: {UNSLASHED}\n" in prompt
        assert f"Check server running at {UNSLASHED}/health" in prompt
        assert f"{UNSLASHED}//" not in prompt

    def test_rendered_prompt_unaffected_when_value_already_clean(self, monkeypatch):
        """Passes on BOTH sides of the change — normalisation must be a no-op here."""
        monkeypatch.setenv("GILJO_PUBLIC_URL", UNSLASHED)
        prompt = _thin_prompt()
        assert f"Check server running at {UNSLASHED}/health" in prompt
        assert "//health" not in prompt

    def test_rendered_prompt_default_is_ce_localhost(self, monkeypatch):
        """DoD 5 — the CE fallback is preserved. Passes on BOTH sides."""
        monkeypatch.delenv("GILJO_PUBLIC_URL", raising=False)
        prompt = _thin_prompt()
        assert f"- Server URL: {CE_DEFAULT}\n" in prompt
        assert f"Check server running at {CE_DEFAULT}/health" in prompt


class TestReadersNormalise:
    """DoD 3 — every reader returns an unslashed URL for a trailing-slash env.

    Sites 3 and 4 already did this and must keep doing it; sites 1 and 2 did
    not. Same parametrised assertion over all four so the inconsistency cannot
    come back on any one of them.
    """

    def _site_1_conductor(self) -> str:
        from api.endpoints.prompts import _conductor_mcp_url

        return _conductor_mcp_url()

    def _site_2_staging_builder(self) -> str:
        """Site 2 has no accessor of its own — read the value back out of the
        rendered prompt, which is where it does damage."""
        prompt = _thin_prompt()
        match = re.search(r"^- Server URL: (.+)$", prompt, re.MULTILINE)
        assert match, "staging prompt no longer renders a '- Server URL:' line"
        return match.group(1)

    def _site_3_continuation(self) -> str:
        """build_continuation_prompt composes '{public_base}/mcp'."""
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
        """DoD 5 — http://localhost:7272 stays the fallback everywhere.

        Passes on BOTH sides of the change.
        """
        monkeypatch.delenv("GILJO_PUBLIC_URL", raising=False)
        assert self.ALL_SITES[site_name](self) == CE_DEFAULT


class TestBootstrapSetupDownloadUrl:
    """Site 5 — the emitted setup-download URL (`_setup_tools.py`).

    WHAT THIS REACHES: the real ``SetupMiscMixin.bootstrap_setup`` body, the real
    ``get_public_url()`` read, the real f-string that joins host and path, and the
    real ``build_setup_instructions`` render — so the assertion is on the URL text
    an agent is actually handed.

    WHAT IT DOES NOT REACH: the database, ``TokenManager``, and ``FileStaging``.
    Those are substituted, because standing up the async staging flow to exercise
    one string join would be a disproportionate instrument. Stated explicitly at
    EM's instruction — a named partial beats a silent gap.
    """

    async def _bootstrap(self, monkeypatch) -> dict:
        import giljo_mcp.downloads.token_manager as token_manager_mod
        import giljo_mcp.file_staging as file_staging_mod
        import giljo_mcp.services.product_service as product_service_mod
        from giljo_mcp.tools.tool_accessor._setup_tools import SetupMiscMixin

        class _FakeProductService:
            """BE-9523c: bootstrap_setup now resolves a product-binding phase up front.

            This test is scoped to URL normalisation only (see module docstring's
            "named partial beats a silent gap"), so the product lookup is stubbed
            to the "zero products" phase -- unrelated to what this test asserts.
            """

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

            async def stage_combined_setup(self, *args, **kwargs):
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
        """The site-5 symptom: `{server_url}/api/download/...` with a slashed host."""
        monkeypatch.setenv("GILJO_PUBLIC_URL", SLASHED)
        result = await self._bootstrap(monkeypatch)
        rendered = str(result)
        assert f"{UNSLASHED}/api/download/temp/TOKEN123/giljo_setup.zip" in rendered
        assert "//api/download" not in rendered

    async def test_download_url_default_preserved(self, monkeypatch):
        """DoD 5 at site 5. Passes on BOTH sides of the change."""
        monkeypatch.delenv("GILJO_PUBLIC_URL", raising=False)
        result = await self._bootstrap(monkeypatch)
        assert f"{CE_DEFAULT}/api/download/temp/TOKEN123/giljo_setup.zip" in str(result)


class TestAccessorContract:
    """DoD 1 — the accessor itself. New surface; not fail-first evidence."""

    def test_strips_trailing_slash(self, monkeypatch):
        from giljo_mcp.http.url_resolver import get_public_url

        monkeypatch.setenv("GILJO_PUBLIC_URL", SLASHED)
        assert get_public_url() == UNSLASHED

    def test_strips_repeated_slashes_and_surrounding_whitespace(self, monkeypatch):
        """Mirrors the GILJO_PUBLIC_BASE_URL treatment at url_resolver.py:50
        (.strip().rstrip('/')) — a pasted value can carry both."""
        from giljo_mcp.http.url_resolver import get_public_url

        monkeypatch.setenv("GILJO_PUBLIC_URL", "  https://app.giljo.ai//  ")
        assert get_public_url() == UNSLASHED

    def test_unset_returns_ce_default(self, monkeypatch):
        from giljo_mcp.http.url_resolver import get_public_url

        monkeypatch.delenv("GILJO_PUBLIC_URL", raising=False)
        assert get_public_url() == CE_DEFAULT

    def test_set_but_empty_returns_ce_default(self, monkeypatch):
        """Deliberate behaviour change, acked by EM on 2026-08-16.

        The old ``os.environ.get(KEY, default)`` form never fires its default for
        a set-but-empty value: it returns '', and the prompt then renders
        'Check server running at /health'. The accessor treats empty as absent,
        which is what api/saas_endpoints/billing_checkout.py already did with its
        ``or`` form.
        """
        from giljo_mcp.http.url_resolver import get_public_url

        monkeypatch.setenv("GILJO_PUBLIC_URL", "")
        assert get_public_url() == CE_DEFAULT

    def test_public_base_url_is_untouched(self, monkeypatch):
        """Out of scope, explicitly: GILJO_PUBLIC_BASE_URL is the
        security-critical sibling (boot gate, Host pin, MCP audience). The new
        accessor must not read it or be confused for it."""
        from giljo_mcp.http import url_resolver

        monkeypatch.setenv("GILJO_PUBLIC_BASE_URL", "https://pinned.example.com")
        monkeypatch.setenv("GILJO_PUBLIC_URL", SLASHED)
        assert url_resolver.get_public_url() == UNSLASHED


class TestNoDirectReadsSurvive:
    """DoD 2 — name-list, never a count.

    Scans src/ and api/ for any line that reads GILJO_PUBLIC_URL out of the
    environment directly. Matching on 'os.environ/os.getenv on the same line as
    the key' rather than on one literal default form, because
    billing_checkout.py used the ``or`` form and that is exactly how it stayed
    invisible to the audit that opened this project.
    """

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
        """Guard the instrument. A scanner that silently matches nothing would
        make the test above pass forever — the failure mode the sprint laws warn
        about ('suspect the instrument first')."""
        assert self.PATTERN.search('x = os.environ.get("GILJO_PUBLIC_URL", "http://localhost:7272")')
        assert self.PATTERN.search('x = (os.environ.get("GILJO_PUBLIC_URL") or "d").rstrip("/")')
        assert self.PATTERN.search('x = os.getenv("GILJO_PUBLIC_URL")')
        # Prose mentions are not reads and must not be flagged.
        assert not self.PATTERN.search("# Fall back to GILJO_PUBLIC_URL env var")
        assert not self.PATTERN.search('"""Reads MCP URL from GILJO_PUBLIC_URL env-var."""')

    def test_scan_roots_exist(self):
        """A typo'd root would scan nothing and pass vacuously."""
        for root in self.SCAN_ROOTS:
            assert (REPO_ROOT / root).is_dir(), f"scan root {root} missing"
        assert (REPO_ROOT / self.ACCESSOR_FILE).is_file()
        assert os.environ is not None  # module import sanity
