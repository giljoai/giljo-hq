# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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




@pytest.fixture
def test_user():
    pass


@pytest.fixture(autouse=True)
def set_tenant_context():
    pass



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




@pytest.fixture
def probe_client():
    app = FastAPI()

    @app.get("/__probe__")
    async def probe(request: Request):
        return {"base": get_public_base_url(request)}

    wrapped = ProxyHeadersMiddleware(app, trusted_hosts="*")
    return TestClient(wrapped)


@pytest.fixture
def public_downloads_client(tmp_path):
    from api.endpoints import downloads

    app = FastAPI()
    app.include_router(downloads.router)
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts="*")
    return TestClient(wrapped)




class TestHelperAcrossShapes:

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




class TestSlashCommandsZipInstallScriptRendering:

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
        if shape != "ce_localhost":
            assert ":7272" not in content, f"Shape {shape} leaked CE default port :7272 into install.sh"


class TestInstallScriptEndpoint:

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




def _source(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _calls_get_public_base_url_with_request(source: str, func_name: str) -> bool:
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

    def test_site_4_slash_commands_zip_uses_helper(self):
        src = _source("api/endpoints/downloads/bundles.py")
        assert _calls_get_public_base_url_with_request(src, "download_slash_commands"), (
            "Site #4 GET /api/download/slash-commands.zip must call get_public_base_url(request)"
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


    def test_site_10_frontend_config_derives_ws_from_request_base_url(self):
        src = _source("api/endpoints/configuration.py")
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_frontend_configuration":
                body = ast.unparse(node)
                if "request.base_url" in body and ".replace(" in body and "wss://" in body:
                    found = True
        assert found, (
            "Site #10 get_frontend_configuration must derive websocket.url "
            "from request.base_url (via .replace for wss://)"
        )




class TestWebsocketUrlDerivation:

    @pytest.mark.parametrize(("shape", "headers", "expected_base", "expected_ws"), ALL_SHAPES)
    def test_ws_url_derived_from_request_base_url(self, probe_client, shape, headers, expected_base, expected_ws):
        response = probe_client.get("/__probe__", headers=headers)
        base = response.json()["base"]
        ws_url = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        assert base == expected_base, f"Shape {shape}: base mismatch"
        assert ws_url == expected_ws, f"Shape {shape}: ws mismatch - got {ws_url}"




@pytest.fixture
def frontend_config_client(monkeypatch):
    from types import SimpleNamespace

    from api import app_state
    from api.endpoints import configuration as configuration_module

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

    def test_frontend_config_api_port_null_through_cloudflare(self, frontend_config_client):
        response = frontend_config_client.get(
            "/api/v1/config/frontend",
            headers={"Host": "mcp.example.com", "X-Forwarded-Proto": "https"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["api"]["host"] == "mcp.example.com"
        assert data["api"]["port"] in (None, 443) or "port" not in data["api"]
        assert data["api"]["protocol"] == "https"
        assert data["websocket"]["url"] == "wss://mcp.example.com"

    def test_frontend_config_api_port_numeric_on_ce_localhost(self, frontend_config_client):
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
        response = frontend_config_client.get(
            "/api/v1/config/frontend",
            headers={"Host": "mcp.acme.corp", "X-Forwarded-Proto": "https"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["api"]["host"] == "mcp.acme.corp"
        assert data["api"]["port"] in (None, 443)
        assert data["api"]["protocol"] == "https"




class TestToolAccessorEnvVarPattern:

    def test_site_2_bootstrap_setup_source_uses_public_url_accessor(self):
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




class TestNoExternalHostInUrlBuildCode:

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
        for rel in self.URL_BUILD_FILES:
            path = REPO_ROOT / rel
            content = path.read_text(encoding="utf-8")
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
        known = {
            "api/middleware/security.py",
            "src/giljo_mcp/config_manager.py",
        }
        unexpected = files_with_hits - known
        assert unexpected == set(), (
            f"services.external_host reappeared in URL-build code. Unexpected files: {sorted(unexpected)}"
        )

    def test_url_resolver_does_not_read_config(self):
        src = _source("src/giljo_mcp/http/url_resolver.py")
        assert "external_host" not in src
        assert "get_nested" not in src
        assert (
            "config" not in src.lower().replace("config-based", "").replace("from config", "")
            or "request.base_url" in src
        ), "url_resolver must not read from config - it delegates to request.base_url"
