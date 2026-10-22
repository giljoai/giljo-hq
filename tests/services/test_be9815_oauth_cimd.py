# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import datetime as dt
import socket
import ssl
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from giljo_mcp.services import oauth_cimd
from giljo_mcp.services.oauth_cimd import CimdError, is_cimd_client_id, is_public_address, resolve_cimd_client
from giljo_mcp.services.oauth_service import ResolvedClient


GOOD_URL = "https://client.example.com/oauth/metadata.json"
LOOPBACK_REDIRECT = "http://localhost:53682/callback"


@pytest.fixture(autouse=True)
def _clean_cache():
    oauth_cimd.clear_cache()
    yield
    oauth_cimd.clear_cache()


def _doc(client_id: str = GOOD_URL, **overrides) -> bytes:
    import json

    body = {"client_id": client_id, "client_name": "Example Client", "redirect_uris": [LOOPBACK_REDIRECT]}
    body.update(overrides)
    return json.dumps(body).encode()




class TestClientIdUrl:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("https://client.example.com/meta.json", True),
            ("http://client.example.com/meta.json", True),
            ("giljo-mcp-default", False),
            ("3f9c2b3e-8a47-4f55-9d52-0f5d4e1d7a11", False),
            ("", False),
            ("ftp://client.example.com/meta.json", False),
        ],
    )
    def test_is_cimd_client_id(self, value, expected):
        assert is_cimd_client_id(value) is expected

    def test_good_url_is_accepted(self):
        assert oauth_cimd.validate_client_id_url(GOOD_URL).hostname == "client.example.com"

    @pytest.mark.parametrize(
        "bad",
        [
            "http://client.example.com/meta.json",
            "https://client.example.com",
            "https://client.example.com/meta.json#frag",
            "https://user:pw@example.com/meta.json",
            "https://client.example.com/a/../meta.json",
            "https://client.example.com/a/./meta.json",
            "https://client.example.com:8443/meta.json",
            "https:///meta.json",
            "https://client.example.com/meta json",
            "https://[::1/meta.json",
            "https://client.example.com\\@10.0.0.1/meta.json",  # noqa: leak-check
            "https://caf\u00e9.example.com/meta.json",
        ],
    )
    def test_bad_url_is_refused(self, bad):
        with pytest.raises(CimdError):
            oauth_cimd.validate_client_id_url(bad)




class TestAddressPolicy:
    @pytest.mark.parametrize("addr", ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"])
    def test_public_addresses_pass(self, addr):
        assert is_public_address(addr) is True

    @pytest.mark.parametrize(
        "addr",
        [
            "127.0.0.1",
            "127.1.2.3",
            "10.0.0.1",  # noqa: leak-check
            "198.18.0.1",
            "192.0.0.8",
            "169.254.169.254",
            "100.64.0.1",
            "100.100.100.200",
            "0.0.0.0",  # noqa: S104 - the value under test is the refused address
            "224.0.0.1",
            "255.255.255.255",
            "::1",
            "::",
            "fe80::1",
            "fc00::1",
            "fd00:ec2::254",
            "::ffff:127.0.0.1",
            "::ffff:10.0.0.1",  # noqa: leak-check
            "::ffff:169.254.169.254",
            "64:ff9b::a00:1",
            "2002:a00:1::",
            "ff02::1",
            "::127.0.0.1",
            "::10.0.0.1",  # noqa: leak-check
            "::a00:1",
            "fec0::1",
            "fec0:0:0:1::5",
            "192.88.99.1",
            "not-an-ip",
        ],
    )
    def test_non_public_addresses_are_refused(self, addr):
        assert is_public_address(addr) is False

    @pytest.mark.asyncio
    async def test_every_resolved_address_must_be_public(self, monkeypatch):
        async def mixed(host, port):
            return ["93.184.216.34", "10.0.0.1"]  # noqa: leak-check

        monkeypatch.setattr(oauth_cimd, "_lookup", mixed)
        with pytest.raises(CimdError):
            await oauth_cimd.resolve_public_address("client.example.com", 443)

    @pytest.mark.asyncio
    async def test_returns_the_first_public_address(self, monkeypatch):
        async def public(host, port):
            return ["93.184.216.34", "93.184.216.35"]

        monkeypatch.setattr(oauth_cimd, "_lookup", public)
        assert await oauth_cimd.resolve_public_address("client.example.com", 443) == "93.184.216.34"

    @pytest.mark.asyncio
    async def test_unresolvable_host_is_refused(self, monkeypatch):
        async def none(host, port):
            return []

        monkeypatch.setattr(oauth_cimd, "_lookup", none)
        with pytest.raises(CimdError):
            await oauth_cimd.resolve_public_address("client.example.com", 443)




class TestDocumentValidation:
    def test_valid_document(self):
        client = oauth_cimd.parse_client_document(GOOD_URL, _doc())
        assert client.client_id == GOOD_URL
        assert client.client_name == "Example Client"
        assert client.redirect_uris == [LOOPBACK_REDIRECT]

    @pytest.mark.parametrize(
        "body",
        [b"", b"not json", b"[]", b'"str"', b"null", b"[" * 5000, b"\xff\xfe"],
    )
    def test_non_object_json_is_refused(self, body):
        with pytest.raises(CimdError):
            oauth_cimd.parse_client_document(GOOD_URL, body)

    def test_client_id_must_equal_the_url_exactly(self):
        with pytest.raises(CimdError):
            oauth_cimd.parse_client_document(GOOD_URL, _doc(client_id=GOOD_URL + "/"))
        with pytest.raises(CimdError):
            oauth_cimd.parse_client_document(GOOD_URL, _doc(client_id="https://CLIENT.example.com/oauth/metadata.json"))
        with pytest.raises(CimdError):
            oauth_cimd.parse_client_document(GOOD_URL, _doc(client_id=None))

    @pytest.mark.parametrize("redirects", [None, [], "http://localhost:1/cb", [123], ["ok", 5], {"a": "b"}])
    def test_redirect_uris_must_be_a_nonempty_list_of_strings(self, redirects):
        with pytest.raises(CimdError):
            oauth_cimd.parse_client_document(GOOD_URL, _doc(redirect_uris=redirects))

    @pytest.mark.parametrize(
        "redirects",
        [
            [""],
            ["http://localhost:1/cb#frag"],
            ["http://localhost@evil.test/cb"],
            ["http://localhost.evil.test/cb"],
            ["x"],
        ],
    )
    def test_a_document_with_no_acceptable_redirect_is_refused(self, redirects):
        with pytest.raises(CimdError):
            oauth_cimd.parse_client_document(GOOD_URL, _doc(redirect_uris=redirects))

    def test_too_many_redirect_uris(self):
        uris = [f"http://localhost:{p}/cb" for p in range(2000, 2000 + oauth_cimd.CIMD_MAX_REDIRECT_URIS + 1)]
        with pytest.raises(CimdError):
            oauth_cimd.parse_client_document(GOOD_URL, _doc(redirect_uris=uris))

    @pytest.mark.parametrize("mode", ["ce", "", "saas"])
    def test_every_edition_accepts_https_and_loopback_redirects(self, monkeypatch, mode):
        monkeypatch.setenv("GILJO_MODE", mode)
        client = oauth_cimd.parse_client_document(
            GOOD_URL, _doc(redirect_uris=["https://client.example.com/cb", LOOPBACK_REDIRECT])
        )
        assert client.redirect_uris == ["https://client.example.com/cb", LOOPBACK_REDIRECT]

    @pytest.mark.parametrize("mode", ["ce", "", "saas"])
    def test_a_hosted_app_document_with_only_an_https_redirect_is_accepted(self, monkeypatch, mode):
        monkeypatch.setenv("GILJO_MODE", mode)
        client = oauth_cimd.parse_client_document(
            GOOD_URL, _doc(redirect_uris=["https://claude.example.com/api/mcp/auth_callback"])
        )
        assert client.redirect_uris == ["https://claude.example.com/api/mcp/auth_callback"]

    @pytest.mark.parametrize("mode", ["ce", "", "saas"])
    def test_plain_http_non_loopback_redirects_are_dropped_in_every_edition(self, monkeypatch, mode):
        monkeypatch.setenv("GILJO_MODE", mode)
        with pytest.raises(CimdError):
            oauth_cimd.parse_client_document(GOOD_URL, _doc(redirect_uris=["http://client.example.com/cb"]))
        client = oauth_cimd.parse_client_document(
            GOOD_URL, _doc(redirect_uris=["http://client.example.com/cb", "https://client.example.com/cb"])
        )
        assert client.redirect_uris == ["https://client.example.com/cb"]

    def test_https_redirect_matching_stays_exact(self):
        listed = ["https://claude.example.com/api/mcp/auth_callback"]
        assert oauth_cimd.redirect_uri_matches(listed, "https://claude.example.com/api/mcp/auth_callback") is True
        assert oauth_cimd.redirect_uri_matches(listed, "https://claude.example.com:8443/api/mcp/auth_callback") is False
        assert oauth_cimd.redirect_uri_matches(listed, "https://claude.example.com/api/mcp/auth_callback?x=1") is False

    @pytest.mark.parametrize("extra", [{"client_secret": "s3cret"}, {"client_secret_expires_at": 0}])
    def test_documents_carrying_a_client_secret_are_refused(self, extra):
        with pytest.raises(CimdError):
            oauth_cimd.parse_client_document(GOOD_URL, _doc(**extra))

    @pytest.mark.parametrize(
        "extra",
        [
            {"token_endpoint_auth_method": "none"},
            {"token_endpoint_auth_method": "private_key_jwt", "jwks_uri": "https://client.example.com/jwks.json"},
            {"token_endpoint_auth_methods_supported": ["none", "private_key_jwt"]},
            {"grant_types": ["authorization_code", "refresh_token", "urn:ietf:params:oauth:grant-type:jwt-bearer"]},
            {"grant_types": ["something-new"], "response_types": ["code", "id_token"]},
            {"scope": "a b c", "logo_uri": "https://client.example.com/logo.png", "unknown_future_field": {"x": 1}},
        ],
    )
    def test_documents_stating_other_auth_methods_or_grants_are_still_served_as_public_clients(self, extra):
        client = oauth_cimd.parse_client_document(GOOD_URL, _doc(**extra))
        assert client.client_id == GOOD_URL

    def test_client_name_is_untrusted_display_text(self):
        client = oauth_cimd.parse_client_document(GOOD_URL, _doc(client_name="Evil\nName\x1b[31m" + "x" * 500))
        assert "\n" not in client.client_name
        assert "\x1b" not in client.client_name
        assert len(client.client_name) <= oauth_cimd.CIMD_MAX_CLIENT_NAME_LENGTH

    def test_missing_client_name_falls_back_to_the_host(self):
        import json

        body = json.dumps({"client_id": GOOD_URL, "redirect_uris": [LOOPBACK_REDIRECT]}).encode()
        assert oauth_cimd.parse_client_document(GOOD_URL, body).client_name == "client.example.com"




class TestRedirectMatching:
    LISTED = ["http://localhost/callback", "http://127.0.0.1/callback", "https://chatgpt.com/connector/redirect"]

    @pytest.mark.parametrize(
        "requested",
        [
            "http://localhost/callback",
            "http://localhost:53682/callback",
            "http://127.0.0.1:1/callback",
            "http://127.0.0.1/callback",
            "https://chatgpt.com/connector/redirect",
        ],
    )
    def test_loopback_port_is_ignored_and_the_rest_is_exact(self, requested):
        assert oauth_cimd.redirect_uri_matches(self.LISTED, requested) is True

    @pytest.mark.parametrize(
        "requested",
        [
            "http://localhost:53682/other",
            "http://localhost:53682/callback?x=1",
            "http://[::1]:53682/callback",
            "https://localhost:53682/callback",
            "http://localhost.evil.test:53682/callback",
            "http://localhost@evil.test:53682/callback",
            "http://localhost:99999999/callback",
            "http://localhost:53682/callback#frag",
            "https://chatgpt.com:8443/connector/redirect",
            "https://chatgpt.com/connector/redirect/",
            "",
        ],
    )
    def test_everything_else_is_refused(self, requested):
        assert oauth_cimd.redirect_uri_matches(self.LISTED, requested) is False

    def test_a_non_loopback_listed_uri_never_gets_port_leniency(self):
        assert (
            oauth_cimd.redirect_uri_matches(["https://app.example.com/cb"], "https://app.example.com:444/cb") is False
        )




@dataclass
class _Server:
    port: int
    cert_path: Path
    status: int = 200
    extra_headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    delay: float = 0.0
    send_length: bool = True
    requests: list[bytes] = field(default_factory=list)


def _make_cert(tmp_path: Path, dns_name: str) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns_name)])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(dns_name)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / f"{dns_name}.pem"
    key_path = tmp_path / f"{dns_name}.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return cert_path, key_path


@pytest_asyncio.fixture
async def cimd_server(tmp_path, monkeypatch):
    cert_path, key_path = _make_cert(tmp_path, "cimd.test")
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(cert_path, key_path)
    state = _Server(port=0, cert_path=cert_path)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            state.requests.append(head)
            if state.delay:
                await asyncio.sleep(state.delay)
            body = state.body
            headers = {"Content-Type": "application/json", **state.extra_headers}
            if state.send_length:
                headers["Content-Length"] = str(len(body))
            lines = [f"HTTP/1.1 {state.status} X".encode()] + [f"{k}: {v}".encode() for k, v in headers.items()]
            writer.write(b"\r\n".join(lines) + b"\r\n\r\n")
            writer.write(body)
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError, ssl.SSLError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_ctx)
    state.port = server.sockets[0].getsockname()[1]

    client_ctx = ssl.create_default_context(cafile=str(cert_path))
    monkeypatch.setattr(oauth_cimd, "_build_ssl_context", lambda: client_ctx)
    monkeypatch.setattr(oauth_cimd, "_ALLOWED_PORTS", frozenset({None, 443, state.port}))

    async def pinned_to_loopback(host, port):
        return "127.0.0.1"

    monkeypatch.setattr(oauth_cimd, "resolve_public_address", pinned_to_loopback)
    try:
        yield state
    finally:
        server.close()
        await server.wait_closed()


def _url(server: _Server) -> str:
    return f"https://cimd.test:{server.port}/oauth/metadata.json"


@pytest.mark.asyncio
class TestFetchOverTheWire:
    async def test_fetches_the_document_from_the_vetted_address_not_a_fresh_lookup(self, cimd_server):
        url = _url(cimd_server)
        cimd_server.body = _doc(client_id=url)

        client = await resolve_cimd_client(url)

        assert isinstance(client, ResolvedClient)
        assert client.client_id == url
        assert client.redirect_uris == [LOOPBACK_REDIRECT]
        assert client.client_secret_hash is None
        request = cimd_server.requests[0]
        assert request.startswith(b"GET /oauth/metadata.json HTTP/1.1")
        assert f"Host: cimd.test:{cimd_server.port}".encode().lower() in request.lower()

    async def test_large_response_headers_are_tolerated(self, cimd_server):
        url = _url(cimd_server)
        cimd_server.body = _doc(client_id=url)
        cimd_server.extra_headers = {"Content-Security-Policy": "default-src 'self' " + "a" * 13000}
        assert (await resolve_cimd_client(url)).client_id == url

    async def test_a_header_flood_is_refused(self, cimd_server):
        url = _url(cimd_server)
        cimd_server.body = _doc(client_id=url)
        cimd_server.extra_headers = {"X-Flood": "a" * (300 * 1024)}
        with pytest.raises(CimdError):
            await resolve_cimd_client(url)

    async def test_no_store_documents_are_served_and_cached_for_the_minimum(self, cimd_server, monkeypatch):
        url = _url(cimd_server)
        cimd_server.body = _doc(client_id=url)
        cimd_server.extra_headers = {"Cache-Control": "no-store,no-cache,max-age=0"}
        clock = {"now": 1000.0}
        monkeypatch.setattr(oauth_cimd, "_now", lambda: clock["now"])
        await resolve_cimd_client(url)
        await resolve_cimd_client(url)
        assert len(cimd_server.requests) == 1
        clock["now"] += oauth_cimd.CIMD_CACHE_MIN_TTL_SECONDS + 1
        await resolve_cimd_client(url)
        assert len(cimd_server.requests) == 2

    async def test_certificate_for_another_name_is_refused(self, cimd_server, monkeypatch):
        url = _url(cimd_server).replace("cimd.test", "other.test")
        cimd_server.body = _doc(client_id=url)
        with pytest.raises(CimdError):
            await resolve_cimd_client(url)

    async def test_redirect_is_not_followed(self, cimd_server):
        url = _url(cimd_server)
        cimd_server.status = 302
        cimd_server.extra_headers = {"Location": "https://169.254.169.254/latest/meta-data/"}
        with pytest.raises(CimdError):
            await resolve_cimd_client(url)
        assert len(cimd_server.requests) == 1

    async def test_non_200_is_refused(self, cimd_server):
        url = _url(cimd_server)
        cimd_server.status = 404
        with pytest.raises(CimdError):
            await resolve_cimd_client(url)

    async def test_oversize_body_is_refused(self, cimd_server):
        url = _url(cimd_server)
        cimd_server.body = _doc(client_id=url, client_name="x" * (oauth_cimd.CIMD_MAX_DOCUMENT_BYTES + 10))
        with pytest.raises(CimdError):
            await resolve_cimd_client(url)

    async def test_oversize_without_content_length_is_cut_off_while_streaming(self, cimd_server, monkeypatch):
        url = _url(cimd_server)
        cimd_server.body = _doc(client_id=url) + b" " * (oauth_cimd.CIMD_MAX_DOCUMENT_BYTES * 4)
        cimd_server.send_length = False
        with pytest.raises(CimdError):
            await resolve_cimd_client(url)

    async def test_slow_server_times_out(self, cimd_server, monkeypatch):
        monkeypatch.setattr(oauth_cimd, "CIMD_FETCH_TIMEOUT_SECONDS", 0.4)
        url = _url(cimd_server)
        cimd_server.body = _doc(client_id=url)
        cimd_server.delay = 3
        loop = asyncio.get_running_loop()
        started = loop.time()
        with pytest.raises(CimdError):
            await resolve_cimd_client(url)
        assert loop.time() - started < 2

    async def test_second_resolution_is_served_from_cache(self, cimd_server):
        url = _url(cimd_server)
        cimd_server.body = _doc(client_id=url)
        first = await resolve_cimd_client(url)
        second = await resolve_cimd_client(url)
        assert (first.client_id, first.redirect_uris) == (second.client_id, second.redirect_uris)
        assert len(cimd_server.requests) == 1

    async def test_a_failed_url_is_remembered_briefly_then_retried(self, cimd_server, monkeypatch):
        clock = {"now": 1000.0}
        monkeypatch.setattr(oauth_cimd, "_now", lambda: clock["now"])
        url = _url(cimd_server)
        cimd_server.status = 500
        for _ in range(3):
            with pytest.raises(CimdError):
                await resolve_cimd_client(url)
        assert len(cimd_server.requests) == 1

        clock["now"] += oauth_cimd.CIMD_NEGATIVE_TTL_SECONDS + 1
        cimd_server.status = 200
        cimd_server.body = _doc(client_id=url)
        assert (await resolve_cimd_client(url)).client_id == url
        assert len(cimd_server.requests) == 2

    async def test_a_refused_document_is_remembered_too(self, cimd_server):
        url = _url(cimd_server)
        cimd_server.body = b"not json"
        for _ in range(2):
            with pytest.raises(CimdError):
                await resolve_cimd_client(url)
        assert len(cimd_server.requests) == 1

    async def test_cache_entry_expires(self, cimd_server, monkeypatch):
        url = _url(cimd_server)
        cimd_server.body = _doc(client_id=url)
        clock = {"now": 1000.0}
        monkeypatch.setattr(oauth_cimd, "_now", lambda: clock["now"])
        await resolve_cimd_client(url)
        clock["now"] += oauth_cimd.CIMD_CACHE_DEFAULT_TTL_SECONDS - 1
        await resolve_cimd_client(url)
        assert len(cimd_server.requests) == 1
        clock["now"] += 2
        await resolve_cimd_client(url)
        assert len(cimd_server.requests) == 2

    async def test_cache_is_bounded_and_evicts_the_least_recently_used(self, cimd_server, monkeypatch):
        monkeypatch.setattr(oauth_cimd, "CIMD_CACHE_MAX_ENTRIES", 2)
        urls = [f"https://cimd.test:{cimd_server.port}/doc/{index}" for index in range(3)]

        async def resolve(url):
            cimd_server.body = _doc(client_id=url)
            await resolve_cimd_client(url)

        await resolve(urls[0])
        await resolve(urls[1])
        await resolve(urls[0])
        assert len(cimd_server.requests) == 2
        await resolve(urls[2])
        assert oauth_cimd.cache_size() == 2
        before = len(cimd_server.requests)
        await resolve(urls[0])
        assert len(cimd_server.requests) == before
        await resolve(urls[1])
        assert len(cimd_server.requests) == before + 1

    async def test_document_for_another_client_id_is_not_cached_under_this_url(self, cimd_server):
        url = _url(cimd_server)
        cimd_server.body = _doc(client_id="https://victim.example.com/meta.json")
        with pytest.raises(CimdError):
            await resolve_cimd_client(url)
        assert oauth_cimd.cache_size() == 0


class TestCacheTtl:
    @pytest.mark.parametrize(
        ("cache_control", "ttl"),
        [
            ("max-age=600", 600),
            ("public, max-age=86400000", oauth_cimd.CIMD_CACHE_MAX_TTL_SECONDS),
            ("max-age=1", oauth_cimd.CIMD_CACHE_MIN_TTL_SECONDS),
            ("no-store", oauth_cimd.CIMD_CACHE_MIN_TTL_SECONDS),
            ("max-age=abc", oauth_cimd.CIMD_CACHE_DEFAULT_TTL_SECONDS),
            (None, oauth_cimd.CIMD_CACHE_DEFAULT_TTL_SECONDS),
        ],
    )
    def test_ttl_follows_cache_control_within_bounds(self, cache_control, ttl):
        assert oauth_cimd.cache_ttl_seconds(cache_control) == ttl


@pytest.mark.asyncio
class TestStaleServiceOnTransientFailure:
    @pytest.fixture
    async def primed(self, cimd_server, monkeypatch):
        clock = {"now": 1000.0}
        monkeypatch.setattr(oauth_cimd, "_now", lambda: clock["now"])
        url = _url(cimd_server)
        cimd_server.body = _doc(client_id=url)
        await resolve_cimd_client(url)
        clock["now"] += oauth_cimd.CIMD_CACHE_DEFAULT_TTL_SECONDS + 1
        return url, clock

    async def test_a_5xx_after_expiry_serves_the_last_good_metadata(self, cimd_server, primed):
        url, clock = primed
        cimd_server.status = 503
        assert (await resolve_cimd_client(url)).redirect_uris == [LOOPBACK_REDIRECT]
        assert len(cimd_server.requests) == 2

        await resolve_cimd_client(url)
        assert len(cimd_server.requests) == 2

        clock["now"] += oauth_cimd.CIMD_CACHE_MIN_TTL_SECONDS + 1
        cimd_server.status = 200
        cimd_server.body = _doc(client_id=url, client_name="Renamed")
        assert (await resolve_cimd_client(url)).client_name == "Renamed"

    async def test_a_timeout_after_expiry_serves_the_last_good_metadata(self, cimd_server, primed, monkeypatch):
        url, _ = primed
        monkeypatch.setattr(oauth_cimd, "CIMD_FETCH_TIMEOUT_SECONDS", 0.3)
        cimd_server.delay = 3
        assert (await resolve_cimd_client(url)).client_id == url

    async def test_stale_service_ends_after_an_hour(self, cimd_server, primed):
        url, clock = primed
        clock["now"] += oauth_cimd.CIMD_STALE_MAX_SECONDS + 1
        cimd_server.status = 503
        with pytest.raises(CimdError):
            await resolve_cimd_client(url)

    @pytest.mark.parametrize(
        "change",
        [
            {"status": 404},
            {"status": 302},
            {"body": b"not json"},
            {"body": _doc(client_id="https://victim.example.com/meta.json")},
        ],
        ids=["gone", "redirect", "garbage", "other-client-id"],
    )
    async def test_a_withdrawn_or_changed_document_is_not_served_stale(self, cimd_server, primed, change):
        url, _ = primed
        for attribute, value in change.items():
            setattr(cimd_server, attribute, value)
        with pytest.raises(CimdError):
            await resolve_cimd_client(url)

    async def test_a_host_that_now_resolves_privately_is_not_served_stale(self, cimd_server, primed, monkeypatch):
        url, _ = primed

        async def private(host, port):
            raise CimdError("client_id host resolves to a non-public address")

        monkeypatch.setattr(oauth_cimd, "resolve_public_address", private)
        with pytest.raises(CimdError):
            await resolve_cimd_client(url)


@pytest.mark.asyncio
class TestResourceBounds:
    async def test_concurrent_misses_for_one_url_share_one_fetch(self, cimd_server):
        url = _url(cimd_server)
        cimd_server.body = _doc(client_id=url)
        cimd_server.delay = 0.3

        results = await asyncio.gather(*(resolve_cimd_client(url) for _ in range(6)))

        assert len(cimd_server.requests) == 1
        assert {r.client_id for r in results} == {url}

    async def test_a_full_house_is_refused_not_queued(self, cimd_server, monkeypatch):
        monkeypatch.setattr(oauth_cimd, "_fetch_slots", asyncio.Semaphore(2))
        cimd_server.delay = 0.6
        urls = [f"https://cimd.test:{cimd_server.port}/doc/{index}" for index in range(3)]
        cimd_server.body = _doc(client_id=urls[0])

        slow = [asyncio.ensure_future(resolve_cimd_client(url)) for url in urls[:2]]
        await asyncio.sleep(0.1)
        loop = asyncio.get_running_loop()
        started = loop.time()
        with pytest.raises(CimdError):
            await resolve_cimd_client(urls[2])
        assert loop.time() - started < 0.3
        await asyncio.gather(*slow, return_exceptions=True)

    async def test_a_refused_full_house_is_not_remembered_as_a_bad_url(self, cimd_server, monkeypatch):
        sem = asyncio.Semaphore(1)
        monkeypatch.setattr(oauth_cimd, "_fetch_slots", sem)
        url = _url(cimd_server)
        cimd_server.body = _doc(client_id=url)
        await sem.acquire()
        with pytest.raises(CimdError):
            await resolve_cimd_client(url)
        sem.release()
        assert (await resolve_cimd_client(url)).client_id == url


@pytest.mark.asyncio
class TestDnsLookupsStayOffTheDefaultPool:
    async def test_lookups_run_on_the_dedicated_executor(self, monkeypatch):
        seen = []

        def record(host, port, family, type_):
            seen.append(threading.current_thread().name)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        monkeypatch.setattr(socket, "getaddrinfo", record)
        assert await oauth_cimd._lookup("client.example.com", 443) == ["93.184.216.34"]
        assert seen[0].startswith("cimd-dns")

    async def test_slow_lookups_do_not_stall_to_thread_and_excess_is_refused(self, monkeypatch):
        release = threading.Event()

        def blocked(host, port, family, type_):
            release.wait(10)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        monkeypatch.setattr(socket, "getaddrinfo", blocked)
        pending = [
            asyncio.ensure_future(oauth_cimd._lookup(f"h{n}.example.com", 443))
            for n in range(oauth_cimd.CIMD_MAX_DNS_LOOKUPS)
        ]
        await asyncio.sleep(0.1)
        try:
            loop = asyncio.get_running_loop()
            started = loop.time()
            assert await asyncio.wait_for(asyncio.to_thread(lambda: 7), 1) == 7
            assert loop.time() - started < 0.5
            with pytest.raises(CimdError):
                await oauth_cimd._lookup("one-too-many.example.com", 443)
        finally:
            release.set()
            await asyncio.gather(*pending)
        assert oauth_cimd._dns_in_flight == 0


@pytest.mark.asyncio
class TestNoNetworkForRefusedTargets:
    async def test_http_client_id_never_touches_the_network(self, monkeypatch):
        async def boom(*args, **kwargs):
            raise AssertionError("network touched")

        monkeypatch.setattr(oauth_cimd, "_lookup", boom)
        monkeypatch.setattr(oauth_cimd, "fetch_document", boom)
        with pytest.raises(CimdError):
            await resolve_cimd_client("http://client.example.com/meta.json")

    @pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fd00:ec2::254"])  # noqa: leak-check
    async def test_host_resolving_to_a_non_public_address_never_connects(self, monkeypatch, address):
        async def lookup(host, port):
            return [address]

        async def boom(*args, **kwargs):
            raise AssertionError("connected to a non-public address")

        monkeypatch.setattr(oauth_cimd, "_lookup", lookup)
        monkeypatch.setattr(oauth_cimd, "fetch_document", boom)
        with pytest.raises(CimdError):
            await resolve_cimd_client(GOOD_URL)
