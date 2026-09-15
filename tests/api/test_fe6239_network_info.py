# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from api.endpoints import configuration as cfg


def _patch_config(monkeypatch, services: dict) -> None:
    import giljo_mcp._config_io as cio

    monkeypatch.setattr(cio, "read_config", lambda: {"services": services})


def _patch_ips(monkeypatch, ips: list[str]) -> None:
    import installer.shared.network as net

    monkeypatch.setattr(net, "get_network_ips", lambda *a, **k: list(ips))


class TestNetworkInfoHostComputation:

    @pytest.mark.asyncio
    async def test_bind_all_enumerates_interface_ips(self, monkeypatch):
        _patch_config(monkeypatch, {"api": {"host": "0.0.0.0", "port": 7272}})
        _patch_ips(monkeypatch, ["192.0.2.100", "198.51.100.5"])

        result = await cfg.get_network_info(current_user=None, _ce=None)

        assert result.hosts == ["192.0.2.100", "198.51.100.5"]
        assert result.host_display == "192.0.2.100, 198.51.100.5"
        assert result.bind_all is True
        assert result.port == 7272

    @pytest.mark.asyncio
    async def test_bind_all_with_no_ips_falls_back_to_localhost(self, monkeypatch):
        _patch_config(monkeypatch, {"api": {"host": "0.0.0.0", "port": 7272}})
        _patch_ips(monkeypatch, [])

        result = await cfg.get_network_info(current_user=None, _ce=None)

        assert result.hosts == ["localhost"]
        assert result.bind_all is True

    @pytest.mark.asyncio
    async def test_loopback_bind_reports_localhost(self, monkeypatch):
        _patch_config(monkeypatch, {"api": {"host": "127.0.0.1", "port": 7272}})
        _patch_ips(monkeypatch, ["192.0.2.100"])

        result = await cfg.get_network_info(current_user=None, _ce=None)

        assert result.hosts == ["localhost"]
        assert result.bind_all is False

    @pytest.mark.asyncio
    async def test_specific_bound_ip_is_the_only_host(self, monkeypatch):
        _patch_config(monkeypatch, {"api": {"host": "203.0.113.5", "port": 9000}})
        _patch_ips(monkeypatch, ["should-not-be-used"])

        result = await cfg.get_network_info(current_user=None, _ce=None)

        assert result.hosts == ["203.0.113.5"]
        assert result.bind_all is False
        assert result.port == 9000

    @pytest.mark.asyncio
    async def test_missing_host_defaults_to_bind_all(self, monkeypatch):
        _patch_config(monkeypatch, {})
        _patch_ips(monkeypatch, ["192.0.2.100"])

        result = await cfg.get_network_info(current_user=None, _ce=None)

        assert result.hosts == ["192.0.2.100"]
        assert result.bind_all is True
        assert result.port == 7272

    @pytest.mark.asyncio
    async def test_port_falls_back_to_frontend_then_default(self, monkeypatch):
        _patch_config(monkeypatch, {"api": {"host": "127.0.0.1"}, "frontend": {"port": 8080}})
        _patch_ips(monkeypatch, [])

        result = await cfg.get_network_info(current_user=None, _ce=None)

        assert result.port == 8080
