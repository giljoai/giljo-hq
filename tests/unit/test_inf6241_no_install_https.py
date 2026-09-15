# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))




@pytest.fixture(scope="module")
def install_module():
    import install  # noqa: PLC0415

    return install


@pytest.fixture(scope="module")
def unified_installer_class(install_module):
    return install_module.UnifiedInstaller


def test_no_setup_https(unified_installer_class):
    assert not hasattr(unified_installer_class, "setup_https"), (
        "setup_https() was removed in INF-6241 (install-time cert factory gone); re-introduction detected"
    )


def test_no_regenerate_cert(install_module):
    assert not hasattr(install_module, "regenerate_cert"), (
        "regenerate_cert() was removed in INF-6241; re-introduction detected"
    )


def test_no_install_mkcert(unified_installer_class):
    assert not hasattr(unified_installer_class, "_install_mkcert"), (
        "_install_mkcert() was removed in INF-6241; re-introduction detected"
    )


def test_no_find_windows_shim(unified_installer_class):
    assert not hasattr(unified_installer_class, "_find_windows_shim"), (
        "_find_windows_shim() was removed in INF-6241; re-introduction detected"
    )




@pytest.fixture(scope="module")
def startup_module():
    import startup  # noqa: PLC0415

    return startup


def test_no_heal_cert_for_ip_drift(startup_module):
    assert not hasattr(startup_module, "_heal_cert_for_ip_drift"), (
        "_heal_cert_for_ip_drift() was removed in INF-6241 (startup DHCP cert self-heal "
        "gone alongside install-time cert factory); re-introduction detected"
    )




@pytest.fixture(scope="module")
def install_source(install_module) -> str:
    return Path(install_module.__file__).read_text(encoding="utf-8").lower()


def test_install_source_free_of_mkcert(install_source):
    assert "mkcert" not in install_source, (
        "Found 'mkcert' token in install.py source — re-introduction of the removed cert factory detected (INF-6241)"
    )


def test_install_source_free_of_giljo_enable_https(install_source):
    assert "giljo_enable_https" not in install_source, (
        "Found 'giljo_enable_https' in install.py source — re-introduction detected (INF-6241)"
    )


def test_install_source_free_of_ssl_opt_out(install_source):
    assert "ssl_opt_out" not in install_source, (
        "Found 'ssl_opt_out' in install.py source — re-introduction detected (INF-6241)"
    )
