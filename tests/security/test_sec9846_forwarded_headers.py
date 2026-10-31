# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import httpx
import pytest

import api.run_api as run_api_mod


REPO_ROOT = Path(__file__).resolve().parents[2]

_SERVER_SCRIPT = textwrap.dedent(
    """
    import sys
    import uvicorn
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    wrap, proxy_headers, port = sys.argv[1] == "wrap", sys.argv[2] == "1", int(sys.argv[3])

    async def who(request):
        return JSONResponse({"ip": request.client.host, "scheme": request.url.scheme})

    app = Starlette(routes=[Route("/who", who)])
    if wrap:
        from api.middleware.trusted_proxy_headers import TrustedProxyHeadersMiddleware
        app = TrustedProxyHeadersMiddleware(app)
    uvicorn.run(app, host="127.0.0.1", port=port, proxy_headers=proxy_headers, log_level="error")
    """
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def serve(tmp_path, monkeypatch):
    procs: list[subprocess.Popen] = []
    script = tmp_path / "serve.py"
    script.write_text(_SERVER_SCRIPT, encoding="utf-8")

    def _start(*, wrap: bool, proxy_headers: bool, env: dict[str, str] | None = None) -> str:
        import os

        port = _free_port()
        child_env = {k: v for k, v in os.environ.items() if k not in {"GILJO_TRUSTED_PROXIES", "FORWARDED_ALLOW_IPS"}}
        child_env["PYTHONPATH"] = str(REPO_ROOT)
        child_env.update(env or {})
        proc = subprocess.Popen(
            [sys.executable, str(script), "wrap" if wrap else "raw", "1" if proxy_headers else "0", str(port)],
            env=child_env,
            cwd=str(REPO_ROOT),
        )
        procs.append(proc)
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                httpx.get(base + "/who", timeout=1)
                return base
            except httpx.HTTPError:
                time.sleep(0.2)
        raise RuntimeError("test server did not start")

    yield _start
    for proc in procs:
        proc.terminate()
        proc.wait(timeout=10)


FORGED = {"X-Forwarded-For": "203.0.113.10"}


def test_launcher_turns_uvicorn_proxy_headers_off(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_run(app, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(run_api_mod, "uvicorn", type("_FakeUvicorn", (), {"run": staticmethod(fake_run)})())
    monkeypatch.setattr(run_api_mod, "__file__", str(tmp_path / "api" / "run_api.py"))
    monkeypatch.setattr(sys, "argv", ["run_api.py", "--port", "19875"])
    run_api_mod.main()

    assert captured.get("proxy_headers") is False


def test_control_default_uvicorn_lets_loopback_forge_the_client(serve):
    base = serve(wrap=False, proxy_headers=True)
    assert httpx.get(base + "/who", headers=FORGED).json()["ip"] == "203.0.113.10"


def test_loopback_cannot_forge_client_when_uvicorn_handling_is_off(serve):
    base = serve(wrap=True, proxy_headers=False)
    body = httpx.get(base + "/who", headers={**FORGED, "CF-Connecting-IP": "198.51.100.7"}).json()
    assert body["ip"] == "127.0.0.1"


def test_configured_trusted_proxy_is_believed(serve):
    base = serve(wrap=True, proxy_headers=False, env={"GILJO_TRUSTED_PROXIES": "127.0.0.1"})
    assert httpx.get(base + "/who", headers=FORGED).json()["ip"] == "203.0.113.10"
    cf = httpx.get(base + "/who", headers={**FORGED, "CF-Connecting-IP": "198.51.100.7"}).json()
    assert cf["ip"] == "198.51.100.7"


def test_trusted_proxy_range_not_containing_peer_is_not_believed(serve):
    base = serve(wrap=True, proxy_headers=False, env={"GILJO_TRUSTED_PROXIES": "192.0.2.0/24"})
    assert httpx.get(base + "/who", headers=FORGED).json()["ip"] == "127.0.0.1"


def test_forwarded_proto_still_honored_from_forwarded_allow_ips_peer(serve):
    base = serve(wrap=True, proxy_headers=False)
    assert httpx.get(base + "/who", headers={"X-Forwarded-Proto": "https"}).json()["scheme"] == "https"


def test_forwarded_proto_ignored_from_untrusted_peer(serve):
    base = serve(wrap=True, proxy_headers=False, env={"FORWARDED_ALLOW_IPS": "192.0.2.5"})
    assert httpx.get(base + "/who", headers={"X-Forwarded-Proto": "https"}).json()["scheme"] == "http"


def test_railway_shape_cloudflare_peer_resolves_real_client(serve):
    base = serve(wrap=True, proxy_headers=False, env={"FORWARDED_ALLOW_IPS": "*"})
    headers = {"X-Forwarded-For": "6.6.6.6, 198.51.100.7, 104.16.0.1", "CF-Connecting-IP": "198.51.100.7"}
    body = httpx.get(base + "/who", headers=headers).json()
    assert body["ip"] == "198.51.100.7"


def test_railway_shape_with_uvicorn_handling_still_on_resolves_real_client(serve):
    base = serve(wrap=True, proxy_headers=True, env={"FORWARDED_ALLOW_IPS": "*"})
    headers = {"X-Forwarded-For": "6.6.6.6, 198.51.100.7, 104.16.0.1", "CF-Connecting-IP": "198.51.100.7"}
    assert httpx.get(base + "/who", headers=headers).json()["ip"] == "198.51.100.7"


@pytest.mark.parametrize("path", ["/who", "/mcp"])
def test_dispatcher_applies_resolver_to_both_planes(monkeypatch, path):
    from starlette.responses import JSONResponse
    from starlette.testclient import TestClient

    from api.mcp_dispatcher import McpDispatcher

    monkeypatch.setenv("GILJO_TRUSTED_PROXIES", "192.0.2.0/24")

    async def echo(scope, receive, send):
        await JSONResponse({"ip": scope["client"][0]})(scope, receive, send)

    client = TestClient(McpDispatcher(echo, echo), client=("192.0.2.3", 5000))
    assert client.get(path, headers=FORGED).json()["ip"] == "203.0.113.10"

    monkeypatch.setenv("GILJO_TRUSTED_PROXIES", "")
    client = TestClient(McpDispatcher(echo, echo), client=("127.0.0.1", 5000))
    assert client.get(path, headers=FORGED).json()["ip"] == "127.0.0.1"


def test_star_forwarded_allow_ips_logs_no_malformed_warning(monkeypatch, caplog):
    from api.middleware.trusted_proxy_headers import TrustedProxyHeadersMiddleware

    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    with caplog.at_level("WARNING"):
        TrustedProxyHeadersMiddleware(app=lambda *a: None)
    assert "malformed" not in caplog.text


def test_malformed_forwarded_allow_ips_warning_names_that_setting(monkeypatch, caplog):
    from api.middleware.trusted_proxy_headers import TrustedProxyHeadersMiddleware

    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "not-an-ip")
    with caplog.at_level("WARNING"):
        TrustedProxyHeadersMiddleware(app=lambda *a: None)
    assert "FORWARDED_ALLOW_IPS" in caplog.text
    assert "GILJO_TRUSTED_PROXIES" not in caplog.text
