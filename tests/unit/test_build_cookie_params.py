# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from unittest.mock import MagicMock, patch

from api.endpoints.auth import _build_cookie_params


class TestBuildCookieParams:

    def _make_request(self, host_header: str = "192.0.2.10:7272") -> MagicMock:
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = host_header.split(":", maxsplit=1)[0]
        request.headers = {"host": host_header}
        request.url.scheme = "http"
        return request


    @patch("api.endpoints.auth.session.get_config")
    def test_returns_dict_with_required_keys(self, mock_config):
        mock_config.return_value = {"security": {"cookies": {"secure": False}}}
        request = self._make_request("127.0.0.1:7272")

        result = _build_cookie_params(request)

        expected_keys = {"key", "httponly", "secure", "samesite", "path", "domain", "max_age"}
        assert set(result.keys()) == expected_keys

    @patch("api.endpoints.auth.session.get_config")
    def test_default_values(self, mock_config):
        mock_config.return_value = {"security": {"cookies": {"secure": False}}}
        request = self._make_request("127.0.0.1:7272")

        result = _build_cookie_params(request)

        assert result["key"] == "access_token"
        assert result["httponly"] is True
        assert result["samesite"] == "lax"
        assert result["path"] == "/"
        assert result["max_age"] == 86400


    @patch("api.endpoints.auth.session.get_config")
    def test_ip_address_omits_cookie_domain(self, mock_config):
        mock_config.return_value = {"security": {"cookies": {"secure": False}}}
        request = self._make_request("192.0.2.10:7272")

        result = _build_cookie_params(request)

        assert result["domain"] is None

    @patch("api.endpoints.auth.session.get_config")
    def test_localhost_ip_omits_cookie_domain(self, mock_config):
        mock_config.return_value = {"security": {"cookies": {"secure": False}}}
        request = self._make_request("127.0.0.1:7272")

        result = _build_cookie_params(request)

        assert result["domain"] is None

    @patch("api.endpoints.auth.session.get_config")
    def test_ip_without_port_omits_cookie_domain(self, mock_config):
        mock_config.return_value = {"security": {"cookies": {"secure": False}}}
        request = self._make_request("192.0.2.100")
        request.headers = {"host": "192.0.2.100"}

        result = _build_cookie_params(request)

        assert result["domain"] is None


    @patch("api.endpoints.auth.session.get_config")
    def test_whitelisted_domain_sets_cookie_domain(self, mock_config):
        mock_config.return_value = {
            "security": {
                "cookies": {"secure": True},
                "cookie_domain_whitelist": ["myapp.example.com"],
            }
        }
        request = self._make_request("myapp.example.com:7272")

        result = _build_cookie_params(request)

        assert result["domain"] == "myapp.example.com"

    @patch("api.endpoints.auth.session.get_config")
    def test_non_whitelisted_domain_returns_none(self, mock_config):
        mock_config.return_value = {
            "security": {
                "cookies": {"secure": False},
                "cookie_domain_whitelist": ["trusted.example.com"],
            }
        }
        request = self._make_request("evil.com:7272")

        result = _build_cookie_params(request)

        assert result["domain"] is None

    @patch("api.endpoints.auth.session.get_config")
    def test_empty_whitelist_domain_returns_none(self, mock_config):
        mock_config.return_value = {
            "security": {
                "cookies": {"secure": False},
                "cookie_domain_whitelist": [],
            }
        }
        request = self._make_request("somehost.local:7272")

        result = _build_cookie_params(request)

        assert result["domain"] is None

    @patch("api.endpoints.auth.session.get_config")
    def test_no_whitelist_key_defaults_empty(self, mock_config):
        mock_config.return_value = {"security": {"cookies": {"secure": False}}}
        request = self._make_request("example.com:7272")

        result = _build_cookie_params(request)

        assert result["domain"] is None


    @patch("api.endpoints.auth.session.get_config")
    def test_secure_flag_from_config(self, mock_config):
        mock_config.return_value = {"security": {"cookies": {"secure": True}}}
        request = self._make_request("127.0.0.1:7272")
        request.url.scheme = ""

        result = _build_cookie_params(request)

        assert result["secure"] is True

    @patch("api.endpoints.auth.session.get_config")
    def test_secure_flag_defaults_false(self, mock_config):
        mock_config.return_value = {}
        request = self._make_request("127.0.0.1:7272")

        result = _build_cookie_params(request)

        assert result["secure"] is False


    @patch("api.endpoints.auth.session.get_config")
    def test_https_scheme_upgrades_secure(self, mock_config):
        mock_config.return_value = {"security": {"cookies": {"secure": False}}}
        request = self._make_request("app.example.com:443")
        request.url.scheme = "https"

        result = _build_cookie_params(request)

        assert result["secure"] is True

    @patch("api.endpoints.auth.session.get_config")
    def test_http_scheme_keeps_secure_false(self, mock_config):
        mock_config.return_value = {"security": {"cookies": {"secure": False}}}
        request = self._make_request("127.0.0.1:7272")

        result = _build_cookie_params(request)

        assert result["secure"] is False

    @patch("api.endpoints.auth.session.get_config")
    def test_http_scheme_downgrades_stale_config_secure_true(self, mock_config):
        mock_config.return_value = {"security": {"cookies": {"secure": True}}}
        request = self._make_request("127.0.0.1:7272")

        result = _build_cookie_params(request)

        assert result["secure"] is False

    @patch("api.endpoints.auth.session.get_config")
    def test_config_secure_true_used_when_no_request_scheme(self, mock_config):
        mock_config.return_value = {"security": {"cookies": {"secure": True}}}
        request = MagicMock()
        request.client = None
        request.url.scheme = ""

        result = _build_cookie_params(request)

        assert result["secure"] is True


    @patch("api.endpoints.auth.session.get_config")
    def test_no_client_returns_domain_none(self, mock_config):
        mock_config.return_value = {"security": {"cookies": {"secure": False}}}
        request = MagicMock()
        request.client = None

        result = _build_cookie_params(request)

        assert result["domain"] is None

    @patch("api.endpoints.auth.session.get_config")
    def test_empty_host_header_returns_domain_none(self, mock_config):
        mock_config.return_value = {"security": {"cookies": {"secure": False}}}
        request = MagicMock()
        request.client = MagicMock()
        request.headers = {"host": ""}

        result = _build_cookie_params(request)

        assert result["domain"] is None

    @patch("api.endpoints.auth.session.get_config")
    def test_missing_host_header_returns_domain_none(self, mock_config):
        mock_config.return_value = {"security": {"cookies": {"secure": False}}}
        request = MagicMock()
        request.client = MagicMock()
        request.headers = {}

        result = _build_cookie_params(request)

        assert result["domain"] is None

    @patch("api.endpoints.auth.session.get_config")
    def test_host_case_insensitive(self, mock_config):
        mock_config.return_value = {
            "security": {
                "cookies": {"secure": False},
                "cookie_domain_whitelist": ["myapp.example.com"],
            }
        }
        request = self._make_request("MyApp.Example.COM:7272")

        result = _build_cookie_params(request)

        assert result["domain"] == "myapp.example.com"


    @patch("api.endpoints.auth.session.get_config")
    def test_uses_cookie_domain_whitelist_not_cookie_domains(self, mock_config):
        mock_config.return_value = {
            "security": {
                "cookies": {"secure": False},
                "cookie_domains": ["old-key-domain.com"],
                "cookie_domain_whitelist": ["correct-domain.com"],
            }
        }
        request = self._make_request("correct-domain.com:7272")

        result = _build_cookie_params(request)

        assert result["domain"] == "correct-domain.com"

    @patch("api.endpoints.auth.session.get_config")
    def test_old_cookie_domains_key_ignored(self, mock_config):
        mock_config.return_value = {
            "security": {
                "cookies": {"secure": False},
                "cookie_domains": ["only-in-old-key.com"],
            }
        }
        request = self._make_request("only-in-old-key.com:7272")

        result = _build_cookie_params(request)

        assert result["domain"] is None


    @patch("api.endpoints.auth.session.get_config")
    def test_db_domain_honored_when_file_config_empty(self, mock_config):
        mock_config.return_value = {"security": {"cookies": {"secure": False}}}
        request = self._make_request("db-only.example.com:7272")

        result = _build_cookie_params(request, db_cookie_domains=["db-only.example.com"])

        assert result["domain"] == "db-only.example.com"

    @patch("api.endpoints.auth.session.get_config")
    def test_file_config_still_honored_when_db_empty(self, mock_config):
        mock_config.return_value = {
            "security": {
                "cookies": {"secure": False},
                "cookie_domain_whitelist": ["legacy-file.example.com"],
            }
        }
        request = self._make_request("legacy-file.example.com:7272")

        result = _build_cookie_params(request, db_cookie_domains=[])

        assert result["domain"] == "legacy-file.example.com"

    @patch("api.endpoints.auth.session.get_config")
    def test_file_and_db_domains_are_unioned(self, mock_config):
        mock_config.return_value = {
            "security": {
                "cookies": {"secure": False},
                "cookie_domain_whitelist": ["file.example.com"],
            }
        }

        file_host = self._make_request("file.example.com:7272")
        db_host = self._make_request("db.example.com:7272")

        assert _build_cookie_params(file_host, db_cookie_domains=["db.example.com"])["domain"] == "file.example.com"
        assert _build_cookie_params(db_host, db_cookie_domains=["db.example.com"])["domain"] == "db.example.com"

    @patch("api.endpoints.auth.session.get_config")
    def test_db_domain_not_matching_host_returns_none(self, mock_config):
        mock_config.return_value = {"security": {"cookies": {"secure": False}}}
        request = self._make_request("evil.example.com:7272")

        result = _build_cookie_params(request, db_cookie_domains=["trusted.example.com"])

        assert result["domain"] is None
