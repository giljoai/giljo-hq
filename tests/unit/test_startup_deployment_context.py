# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_STARTUP_PATH = Path(__file__).resolve().parents[2] / "startup.py"


@pytest.fixture(scope="module")
def startup_module():
    spec = importlib.util.spec_from_file_location("_giljo_startup_under_test", _STARTUP_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_yaml(tmp_path: Path, body: str) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(body, encoding="utf-8")
    return cfg


def test_returns_localhost_when_key_missing(startup_module, tmp_path, monkeypatch):
    _write_yaml(tmp_path, "services:\n  external_host: ''\n")
    monkeypatch.chdir(tmp_path)
    assert startup_module.get_deployment_context() == "localhost"


def test_returns_saas_production_when_explicitly_set(startup_module, tmp_path, monkeypatch):
    _write_yaml(tmp_path, "deployment_context: saas-production\n")
    monkeypatch.chdir(tmp_path)
    assert startup_module.get_deployment_context() == "saas-production"


def test_returns_localhost_when_no_config_file(startup_module, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert startup_module.get_deployment_context() == "localhost"


def test_external_host_read_from_services_block(startup_module, tmp_path, monkeypatch):
    _write_yaml(
        tmp_path,
        "deployment_context: localhost\nservices:\n  external_host: mcp.example.com\n",
    )
    monkeypatch.chdir(tmp_path)
    assert startup_module._get_external_host() == "mcp.example.com"


def test_external_host_empty_when_absent(startup_module, tmp_path, monkeypatch):
    _write_yaml(tmp_path, "deployment_context: localhost\n")
    monkeypatch.chdir(tmp_path)
    assert startup_module._get_external_host() == ""
