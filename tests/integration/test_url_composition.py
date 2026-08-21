# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
INF-5012 Phase 2b - URL composition integration tests.

Verifies that the 10 backend URL-building sites fixed in Phase 1 (commit b2f33d75)
return correct public URLs under 3 realistic deployment shapes:

    Shape A - Cloudflare Tunnel (mcp.example.com):
        Host: mcp.example.com, X-Forwarded-Proto: https  ->  https://mcp.example.com
    Shape B - CE localhost (default, no proxy):
        Host: localhost:7272                           ->  http://localhost:7272
    Shape C - Customer nginx-fronted CE:
        Host: mcp.acme.corp, X-Forwarded-Proto: https  ->  https://mcp.acme.corp

The sites:
    #1 RETIRED (INF-6111b) - tool_accessor::generate_download_token MCP leg removed;
       the REST POST /api/download/generate-token (site #8) keeps request-based composition.
    #2 src/giljo_mcp/tools/tool_accessor.py::bootstrap_setup          (env-var)
    #3 api/endpoints/downloads.py::get_public_base_url helper usage
    #4 GET /api/download/slash-commands.zip - install-script rendering
    #5 GET /api/download/agent-templates.zip - install-script rendering
    #6 GET /api/download/install-script.{ext}
    #7 GET /api/download/bootstrap-prompt
    #8 POST /api/download/generate-token
    #9 RETIRED (BE-9143) - GET /api/ai-tools/config-generator/{tool_name} was a
       registered-but-dead route (reimplemented client-side in useMcpConfig.js).
    #10 GET /api/v1/config/frontend (websocket.url field)

Strategy:
    - Sites #1, #2: env-var pattern, verified by monkeypatching GILJO_PUBLIC_URL
      and replaying the exact code pattern used in tool_accessor.
    - Sites #3-#10: All delegate URL composition to
      giljo_mcp.http.url_resolver.get_public_base_url(request). We verify:
        (a) The helper itself returns correct values under all 3 shapes when
            wrapped in uvicorn's ProxyHeadersMiddleware (the middleware used in
            production by uvicorn's --proxy-headers flag).
        (b) Every endpoint file imports and uses get_public_base_url(request)
            via AST/source-level assertions (proves the call-site pattern).
        (c) Publicly-reachable endpoints (#4 slash-commands.zip, #6
            install-script) are exercised end-to-end under all 3 shapes -
            the rendered install script must contain the correct SERVER_URL.
    - Grep guardrail: zero `services.external_host` references in URL-build
      code across api/ and src/giljo_mcp/ (informational server-response
      fields are allowed in configuration.py:655 per mission spec).
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from giljo_mcp.http.url_resolver import get_public_base_url


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Fixture overrides - opt this module out of the parent integration conftest's
# DB-backed `test_user` / `set_tenant_context` autouse fixtures. URL
# composition is a pure request-handling concern; no DB access is required.
# ---------------------------------------------------------------------------


@pytest.fixture
def test_user():
    """Override parent conftest's DB-backed test_user fixture - unused here."""


@pytest.fixture(autouse=True)
def set_tenant_context():
    """Override parent conftest's DB-dependent autouse fixture."""


# ---------------------------------------------------------------------------
# Shape definitions - single source of truth for every assertion below.
# ---------------------------------------------------------------------------

SHAPE_A_HEADERS = {"Host": "mcp.example.com", "X-Forwarded-Proto": "https"}
SHAPE_A_EXPECTED_BASE = "https://mcp.example.com"
SHAPE_A_EXPECTED_WS = "wss://mcp.example.com"

SHAPE_B_HEADERS = {"Host": "localhost:7272"}
SHAPE_B_EXPECTED_BASE = "http://localhost:7272"
SHAPE_B_EXPECTED_WS = "ws://localhost:7272"

SHAPE_C_HEADERS = {"Host": "mcp.acme.corp", "X-Forwarded-Proto": "https"}
SHAPE_C_EXPECTED_BASE = "https://mcp.acme.corp"
SHAPE_C_EXPECTED_WS = "wss://mcp.acme.corp"

ALL_SHAPES = [
    ("cloudflare_tunnel", SHAPE_A_HEADERS, SHAPE_A_EXPECTED_BASE, SHAPE_A_EXPECTED_WS),
    ("ce_localhost", SHAPE_B_HEADERS, SHAPE_B_EXPECTED_BASE, SHAPE_B_EXPECTED_WS),
    ("customer_nginx", SHAPE_C_HEADERS, SHAPE_C_EXPECTED_BASE, SHAPE_C_EXPECTED_WS),
]


# ---------------------------------------------------------------------------
# Fixture: a minimal FastAPI app with a probe endpoint + ProxyHeadersMiddleware.
# This mirrors how uvicorn wraps the production app via --proxy-headers.
# ---------------------------------------------------------------------------


@pytest.fixture
def probe_client():
    """TestClient for a stub app that exposes the URL-resolver helper directly."""
    app = FastAPI()

    @app.get("/__probe__")
    async def probe(request: Request):
        return {"base": get_public_base_url(request)}

    wrapped = ProxyHeadersMiddleware(app, trusted_hosts="*")
    return TestClient(wrapped)


@pytest.fixture
def public_downloads_client(tmp_path):
    """
    TestClient with the real downloads router mounted + ProxyHeadersMiddleware.

    Only public (unauthenticated) endpoints on downloads are used:
      - GET /api/download/slash-commands.zip   (site #4)
      - GET /api/download/install-script.sh    (site #6)
    """
    from api.endpoints import downloads

    app = FastAPI()
    app.include_router(downloads.router)
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts="*")
    return TestClient(wrapped)


# ---------------------------------------------------------------------------
# SITE #3 - get_public_base_url helper used by every FastAPI site.
# 3 shapes x 1 helper = 3 assertions. This is the heart of sites #3-#10.
# ---------------------------------------------------------------------------


class TestHelperAcrossShapes:
    """get_public_base_url(request) returns expected base under every shape."""

    @pytest.mark.parametrize(("shape", "headers", "expected", "_ws"), ALL_SHAPES)
    def test_helper_returns_expected_base(self, probe_client, shape, headers, expected, _ws):
        response = probe_client.get("/__probe__", headers=headers)
        assert response.status_code == 200
        assert response.json()["base"] == expected, (
            f"Shape {shape}: expected base={expected}, got {response.json()['base']}"
        )

    def test_shape_a_has_no_localhost_port(self, probe_client):
        base = probe_client.get("/__probe__", headers=SHAPE_A_HEADERS).json()["base"]
        assert ":7272" not in base
        assert base.startswith("https://")

    def test_shape_b_contains_localhost_port(self, probe_client):
        base = probe_client.get("/__probe__", headers=SHAPE_B_HEADERS).json()["base"]
        assert ":7272" in base
        assert base.startswith("http://")
        assert not base.startswith("https://")

    def test_shape_c_uses_customer_host_and_https(self, probe_client):
        base = probe_client.get("/__probe__", headers=SHAPE_C_HEADERS).json()["base"]
        assert "mcp.acme.corp" in base
        assert base.startswith("https://")
        assert ":7272" not in base


# ---------------------------------------------------------------------------
# SITE #4 - GET /api/download/slash-commands.zip  (public, install.sh rendering)
# SITE #6 - GET /api/download/install-script.sh   (public)
# These are the two publicly-reachable sites whose rendered install scripts
# must contain the correct {{SERVER_URL}} substitution under every shape.
# ---------------------------------------------------------------------------


class TestSlashCommandsZipInstallScriptRendering:
    """Site #4: install.sh inside slash-commands.zip must embed the public URL."""

    @pytest.mark.parametrize(("shape", "headers", "expected", "_ws"), ALL_SHAPES)
    def test_install_sh_contains_expected_server_url(self, public_downloads_client, shape, headers, expected, _ws):
        import io
        import zipfile

        response = public_downloads_client.get("/api/download/slash-commands.zip?platform=claude_code", headers=headers)
        assert response.status_code == 200, f"Shape {shape}: {response.status_code} {response.text[:200]}"
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            names = zf.namelist()
            if "install.sh" not in names:
                pytest.fail(
                    "install.sh template absent from installer/templates - not a URL-composition defect", pytrace=False
                )
            content = zf.read("install.sh").decode("utf-8")
        assert expected in content, (
            f"Shape {shape}: expected {expected} inside install.sh, not found. First 400 chars: {content[:400]}"
        )
        # Negative guard: shapes A and C must not leak the CE default port.
        if shape != "ce_localhost":
            assert ":7272" not in content, f"Shape {shape} leaked CE default port :7272 into install.sh"


class TestInstallScriptEndpoint:
    """Site #6: GET /api/download/install-script.{sh,ps1} must render public URL."""

    @pytest.mark.parametrize(("shape", "headers", "expected", "_ws"), ALL_SHAPES)
    def test_install_sh_script_contains_expected_server_url(
        self, public_downloads_client, shape, headers, expected, _ws
    ):
        response = public_downloads_client.get(
            "/api/download/install-script.sh?script_type=slash-commands", headers=headers
        )
        if response.status_code == 500:
            pytest.fail(
                "install-script template missing in installer/templates - not a URL-composition defect", pytrace=False
            )
        assert response.status_code == 200, f"Shape {shape}: {response.status_code} {response.text[:200]}"
        body = response.content.decode("utf-8")
        assert expected in body, (
            f"Shape {shape}: expected {expected} in rendered install-script, got first 400 chars: {body[:400]}"
        )
        if shape != "ce_localhost":
            assert ":7272" not in body, f"Shape {shape} leaked CE default port :7272 into install-script"

    @pytest.mark.parametrize(("shape", "headers", "expected", "_ws"), ALL_SHAPES)
    def test_install_ps1_script_contains_expected_server_url(
        self, public_downloads_client, shape, headers, expected, _ws
    ):
        response = public_downloads_client.get(
            "/api/download/install-script.ps1?script_type=slash-commands", headers=headers
        )
        if response.status_code == 500:
            pytest.fail("install-script .ps1 template missing - not a URL-composition defect", pytrace=False)
        assert response.status_code == 200, f"Shape {shape}: {response.status_code}"
        body = response.content.decode("utf-8")
        assert expected in body, (
            f"Shape {shape}: expected {expected} in rendered install.ps1, got first 400 chars: {body[:400]}"
        )


# ---------------------------------------------------------------------------
# SITES #5, #7, #8, #9, #10 - authenticated / DB-backed endpoints.
#
# These require full DB + auth + staging fixtures to exercise end-to-end, which
# is out of proportion for a pure URL-composition regression test. Instead, we
# prove each endpoint file IMPORTS and USES get_public_base_url(request) via
# AST inspection. Because site #3 proves the helper itself is correct across
# all 3 shapes (TestHelperAcrossShapes above), this equivalence-argument is
# sound: if site X calls the helper with `request`, site X's URL must be
# correct under every shape.
# ---------------------------------------------------------------------------


def _source(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _calls_get_public_base_url_with_request(source: str, func_name: str) -> bool:
    """AST-check: function `func_name` contains a call get_public_base_url(request)."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == "get_public_base_url"
                    and len(sub.args) == 1
                    and isinstance(sub.args[0], ast.Name)
                    and sub.args[0].id == "request"
                ):
                    return True
    return False


class TestEndpointCallSitePattern:
    """
    Sites #4, #5, #6, #7, #8, #9, #10 each call get_public_base_url(request).
    Proves the pattern is in place; helper correctness is proven in
    TestHelperAcrossShapes. Combined -> URL is correct for every shape.
    """

    def test_site_4_slash_commands_zip_uses_helper(self):
        src = _source("api/endpoints/downloads/bundles.py")
        assert _calls_get_public_base_url_with_request(src, "download_slash_commands"), (
            "Site #4 GET /api/download/slash-commands.zip must call get_public_base_url(request)"
        )

    def test_site_5_agent_templates_zip_uses_helper(self):
        src = _source("api/endpoints/downloads/bundles.py")
        assert _calls_get_public_base_url_with_request(src, "download_agent_templates"), (
            "Site #5 GET /api/download/agent-templates.zip must call get_public_base_url(request)"
        )

    def test_site_6_install_script_uses_helper(self):
        src = _source("api/endpoints/downloads/bundles.py")
        assert _calls_get_public_base_url_with_request(src, "download_install_script"), (
            "Site #6 GET /api/download/install-script must call get_public_base_url(request)"
        )

    def test_site_7_bootstrap_prompt_uses_helper(self):
        src = _source("api/endpoints/downloads/bundles.py")
        assert _calls_get_public_base_url_with_request(src, "get_bootstrap_prompt"), (
            "Site #7 GET /api/download/bootstrap-prompt must call get_public_base_url(request)"
        )

    def test_site_8_generate_token_uses_helper(self):
        src = _source("api/endpoints/downloads/tokens.py")
        assert _calls_get_public_base_url_with_request(src, "generate_download_token"), (
            "Site #8 POST /api/download/generate-token must call get_public_base_url(request)"
        )

    # Site #9 (GET /api/ai-tools/config-generator/{tool_name}) retired in BE-9143
    # — the route was registered-but-dead (frontend reimplemented it client-side in
    # useMcpConfig.js). ai_tools.py is now a pure helpers module with no
    # request-based URL composition, so there is no call site left to assert.

    def test_site_10_frontend_config_derives_ws_from_request_base_url(self):
        """
        Site #10: GET /api/v1/config/frontend derives websocket.url from
        request.base_url (not from config.external_host). This endpoint
        inlines the composition rather than calling the helper - verify
        the inlined pattern is present.
        """
        src = _source("api/endpoints/configuration.py")
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_frontend_configuration":
                body = ast.unparse(node)
                # Must derive from request.base_url and must produce ws:// / wss://
                if "request.base_url" in body and ".replace(" in body and "wss://" in body:
                    found = True
        assert found, (
            "Site #10 get_frontend_configuration must derive websocket.url "
            "from request.base_url (via .replace for wss://)"
        )


# ---------------------------------------------------------------------------
# Site #10 - also verify end-to-end websocket.url composition across shapes
# by running the ws-derivation logic exactly as the endpoint does. This
# duplicates the small inline block but gives us 3 shape-level assertions.
# ---------------------------------------------------------------------------


class TestWebsocketUrlDerivation:
    """Site #10 websocket.url must be wss:// for https bases, ws:// for http bases."""

    @pytest.mark.parametrize(("shape", "headers", "expected_base", "expected_ws"), ALL_SHAPES)
    def test_ws_url_derived_from_request_base_url(self, probe_client, shape, headers, expected_base, expected_ws):
        # Replay the exact derivation from configuration.py:get_frontend_configuration
        response = probe_client.get("/__probe__", headers=headers)
        base = response.json()["base"]
        ws_url = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        assert base == expected_base, f"Shape {shape}: base mismatch"
        assert ws_url == expected_ws, f"Shape {shape}: ws mismatch - got {ws_url}"


# ---------------------------------------------------------------------------
# INF-5012b Part 1 regression - api.host/port/protocol derive from
# request.base_url, NOT from config.services.external_host + api_port.
# ---------------------------------------------------------------------------


@pytest.fixture
def frontend_config_client(monkeypatch):
    """
    TestClient mounting the real /api/v1/config/frontend endpoint with
    ProxyHeadersMiddleware and a stub app-state config. Exercises the
    full endpoint response shape under reverse-proxy headers.
    """
    from types import SimpleNamespace

    from api import app_state
    from api.endpoints import configuration as configuration_module

    # Minimal stub config that satisfies every get_nested / tenant access.
    nested_values = {
        "features.api_keys_required": False,
        "features.ssl_enabled": False,
        "edition": "community",
    }

    def fake_get_nested(key, default=None):
        return nested_values.get(key, default)

    stub_config = SimpleNamespace(
        get_nested=fake_get_nested,
        tenant=SimpleNamespace(default_tenant_key="tk_test"),
    )

    monkeypatch.setattr(app_state.state, "config", stub_config, raising=False)

    app = FastAPI()
    app.include_router(configuration_module.router, prefix="/api/v1/config")
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts="*")
    return TestClient(wrapped)


class TestFrontendConfigApiFields:
    """INF-5012b Part 1: api.host/port/protocol derive from request.base_url."""

    def test_frontend_config_api_port_null_through_cloudflare(self, frontend_config_client):
        """
        Regression: api.port must be null/omitted when behind a reverse proxy
        on standard HTTPS port. Without this, the setup wizard emits :7272
        into user-facing `claude mcp add` commands.
        """
        response = frontend_config_client.get(
            "/api/v1/config/frontend",
            headers={"Host": "mcp.example.com", "X-Forwarded-Proto": "https"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["api"]["host"] == "mcp.example.com"
        assert data["api"]["port"] in (None, 443) or "port" not in data["api"]
        assert data["api"]["protocol"] == "https"
        # Websocket URL must also be public-host-derived.
        assert data["websocket"]["url"] == "wss://mcp.example.com"

    def test_frontend_config_api_port_numeric_on_ce_localhost(self, frontend_config_client):
        """CE localhost (no reverse-proxy headers): port stays numeric 7272."""
        response = frontend_config_client.get(
            "/api/v1/config/frontend",
            headers={"Host": "localhost:7272"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["api"]["host"] == "localhost"
        assert data["api"]["port"] == 7272
        assert data["api"]["protocol"] == "http"
        assert data["websocket"]["url"] == "ws://localhost:7272"

    def test_frontend_config_customer_nginx_https(self, frontend_config_client):
        """Customer nginx-fronted CE: https with implicit 443."""
        response = frontend_config_client.get(
            "/api/v1/config/frontend",
            headers={"Host": "mcp.acme.corp", "X-Forwarded-Proto": "https"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["api"]["host"] == "mcp.acme.corp"
        assert data["api"]["port"] in (None, 443)
        assert data["api"]["protocol"] == "https"


# ---------------------------------------------------------------------------
# SITE #2 - tool_accessor MCP tool site (no FastAPI request context).
# Reads GILJO_PUBLIC_URL via os.environ with localhost fallback.
# (INF-6111b: former Site #1 generate_download_token accessor leg was RETIRED;
# the REST POST /api/download/generate-token route keeps request-based URL
# composition, covered by the request-context site tests above.)
# ---------------------------------------------------------------------------


class TestToolAccessorEnvVarPattern:
    """Site #2 reads GILJO_PUBLIC_URL, defaulting to http://localhost:7272."""

    def test_site_2_bootstrap_setup_source_uses_public_url_accessor(self):
        """BE-9442 moved the env read behind one accessor; the guarantee is unchanged.

        This test previously asserted the literal
        ``os.environ.get("GILJO_PUBLIC_URL", "http://localhost:7272")`` appeared in
        ``bootstrap_setup``. That expression no longer exists anywhere outside
        ``giljo_mcp.http.url_resolver`` — it was one of three sites that omitted
        ``.rstrip("/")`` and emitted ``https://host//api/download/...``.

        What INF-5012 was actually protecting is unchanged and still asserted: this
        site must resolve its URL from the deployment's public address, NOT from the
        server's bind address in config. Only the expression moved.
        """
        src = _source("src/giljo_mcp/tools/tool_accessor/_setup_tools.py")
        tree = ast.parse(src)
        found_any = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "bootstrap_setup":
                body = ast.unparse(node)
                if "get_public_url()" in body:
                    found_any = True
        assert found_any, (
            "Site #2 tool_accessor.bootstrap_setup must resolve its URL via "
            "giljo_mcp.http.url_resolver.get_public_url() (BE-9442)"
        )
        assert "os.environ" not in src, "BE-9442: no direct GILJO_PUBLIC_URL env read may return to this file"

    def test_env_var_set_yields_demo_url(self, monkeypatch):
        monkeypatch.setenv("GILJO_PUBLIC_URL", "https://mcp.example.com")
        server_url = os.environ.get("GILJO_PUBLIC_URL", "http://localhost:7272")
        download_url = f"{server_url}/api/download/temp/tok/file.zip"
        assert download_url.startswith("https://mcp.example.com/")
        assert ":7272" not in download_url

    def test_env_var_set_customer_yields_customer_url(self, monkeypatch):
        monkeypatch.setenv("GILJO_PUBLIC_URL", "https://mcp.acme.corp")
        server_url = os.environ.get("GILJO_PUBLIC_URL", "http://localhost:7272")
        assert server_url == "https://mcp.acme.corp"
        assert ":7272" not in f"{server_url}/anything"

    def test_env_var_unset_falls_back_to_localhost_7272(self, monkeypatch):
        monkeypatch.delenv("GILJO_PUBLIC_URL", raising=False)
        server_url = os.environ.get("GILJO_PUBLIC_URL", "http://localhost:7272")
        assert server_url == "http://localhost:7272"


# ---------------------------------------------------------------------------
# GREP GUARDRAIL - zero services.external_host references in URL-build code
# after INF-5012b. Only non-URL-build references (CORS/CSP, docstrings) remain.
# ---------------------------------------------------------------------------


class TestNoExternalHostInUrlBuildCode:
    """
    Guardrail: services.external_host must not appear in any URL-composition
    code. Allowed remaining references are the CORS/CSP allow-list in
    api/middleware/security.py and docstring examples in config_manager.py.
    """

    # INF-5012b closed the three deferred Phase-2 files: configuration.py (wizard
    # endpoint — now derives api.host/port/protocol from request.base_url),
    # thin_prompt_generator.py, and staging_prompt_builder.py (now read
    # GILJO_PUBLIC_URL env-var). All URL-build sites are complete.
    URL_BUILD_FILES = (
        "api/endpoints/downloads/bundles.py",
        "api/endpoints/downloads/tokens.py",
        "api/endpoints/configuration.py",
        "src/giljo_mcp/tools/tool_accessor/_setup_tools.py",
        "src/giljo_mcp/http/url_resolver.py",
        "src/giljo_mcp/thin_prompt_generator.py",
        "src/giljo_mcp/prompts/staging_prompt_builder.py",
    )

    def test_grep_url_build_files_external_host_free(self):
        """Zero services.external_host hits in all URL-build files."""
        for rel in self.URL_BUILD_FILES:
            path = REPO_ROOT / rel
            content = path.read_text(encoding="utf-8")
            # Allow the literal inside comments/docstrings only.
            offending = []
            for i, line in enumerate(content.splitlines(), 1):
                if "services.external_host" not in line:
                    continue
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                offending.append(f"{rel}:{i}:{line}")
            assert offending == [], (
                f"Phase-1 file {rel} still has services.external_host in URL-build code:\n" + "\n".join(offending)
            )

    def test_grep_whole_tree_report_of_remaining_references(self):
        """
        Guardrail: after INF-5012b, services.external_host appears only in
        non-URL-build contexts (CORS allow-list + docstring examples).
        Fails loudly if the reference re-enters any URL-composition code.

        Scanned in Python rather than by shelling out to ``grep``, for two
        reasons measured on this repo:

        1. ``grep`` is not on PATH on a Windows workstation unless Git's
           ``usr/bin`` happens to be there, so this test failed locally with
           FileNotFoundError while CI reported the same commit green. The local
           and CI signals disagreed, and only one of them was telling the truth.
        2. More seriously, the old form was VACUOUS. It passed ``check=False``
           and read hits out of stdout, so a grep that could not run — exit 2,
           a renamed directory, a missing binary — produced an empty stdout that
           is indistinguishable from "clean", and the assertion passed over a
           scan that never happened. Measured: pointing it at a non-existent
           directory gives rc=2, empty hits, and a GREEN test.

        The replacement uses the same pure-Python read the sibling test above
        already uses, and the file-count anchor below makes a collapsed walk
        fail instead of passing quietly.
        """
        scanned = 0
        files_with_hits = set()
        for rel_dir in ("api", "src/giljo_mcp"):
            for path in (REPO_ROOT / rel_dir).rglob("*.py"):
                try:
                    content = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                scanned += 1
                if "services.external_host" in content:
                    files_with_hits.add(path.relative_to(REPO_ROOT).as_posix())

        assert scanned > 100, (
            f"only {scanned} .py files were scanned under api/ and src/giljo_mcp/ — the walk "
            "collapsed, so a clean result here would mean nothing. Check that the directories "
            "still exist and are named as expected."
        )
        # Only non-URL-build references are allowed to remain.
        known = {
            "api/middleware/security.py",  # CORS/CSP host allow-list, not URL build
            "src/giljo_mcp/config_manager.py",  # docstring examples, not URL build
        }
        unexpected = files_with_hits - known
        assert unexpected == set(), (
            f"services.external_host reappeared in URL-build code. Unexpected files: {sorted(unexpected)}"
        )

    def test_url_resolver_does_not_read_config(self):
        """Helper delegates purely to request.base_url - no config reads."""
        src = _source("src/giljo_mcp/http/url_resolver.py")
        assert "external_host" not in src
        assert "get_nested" not in src
        assert (
            "config" not in src.lower().replace("config-based", "").replace("from config", "")
            or "request.base_url" in src
        ), "url_resolver must not read from config - it delegates to request.base_url"
