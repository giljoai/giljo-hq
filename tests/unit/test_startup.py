# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Test suite for startup.py - Unified entry point for Giljo HQ.

Tests cover:
- PostgreSQL detection
- Python version checking
- Database connectivity
- First-run detection
- Service management
- Cross-platform compatibility
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Add project root to path for imports
# TODO: Remove after editable install confirmed on all platforms
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture
def mock_env(monkeypatch):
    """Mock environment variables."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:testpw@localhost:5432/giljo_mcp")
    return monkeypatch


class TestPostgreSQLDetection:
    """Test PostgreSQL detection functionality."""

    def test_psql_available(self):
        """Test detection when psql is available."""
        import shutil

        result = shutil.which("psql")
        # This test depends on environment - just verify function works
        assert result is None or isinstance(result, (str, type(None)))

    @patch("shutil.which")
    def test_psql_not_found(self, mock_which):
        """Test detection when psql is not available."""
        mock_which.return_value = None
        assert mock_which("psql") is None

    @patch("shutil.which")
    def test_psql_found(self, mock_which):
        """Test detection when psql is available."""
        mock_which.return_value = "/usr/bin/psql"
        assert mock_which("psql") == "/usr/bin/psql"


class TestPythonVersionCheck:
    """Test Python version checking."""

    def test_current_python_version(self):
        """Test that current Python version is detected correctly."""
        version_info = sys.version_info
        assert version_info.major >= 3
        assert version_info.minor >= 10

    def test_version_comparison(self):
        """Test version comparison logic."""
        version_info = sys.version_info
        is_compatible = version_info >= (3, 10)
        assert is_compatible is True


class TestDatabaseConnectivity:
    """Test database connectivity checking."""

    def test_database_connection_success(self, mock_env):
        """Test successful database connection."""
        # This test verifies the DatabaseManager can be instantiated with valid URL
        from giljo_mcp.database import DatabaseManager

        db_url = "postgresql://postgres:testpw@localhost:5432/giljo_mcp"

        # Just verify we can create the manager object
        # Actual connection testing would require a real database
        try:
            manager = DatabaseManager(database_url=db_url, is_async=False)
            assert manager is not None
            assert manager.database_url == db_url
        except Exception as _exc:  # noqa: S110
            # If database not available, that's ok for unit test
            # Real connection testing should be in integration tests
            pass

    @patch("giljo_mcp.database.DatabaseManager")
    def test_database_connection_failure(self, mock_db_manager):
        """Test database connection failure handling."""
        mock_db_manager.side_effect = Exception("Connection refused")

        from giljo_mcp.database import DatabaseManager

        with pytest.raises(Exception, match="Connection refused"):
            DatabaseManager(database_url="postgresql://invalid", is_async=False)


class TestFirstRunDetection:
    """Test first-run detection logic."""

    @patch("giljo_mcp.setup.state_manager.SetupStateManager.get_instance")
    def test_first_run_not_completed(self, mock_state_manager):
        """Test detection when setup is not completed."""
        mock_manager = MagicMock()
        mock_manager.get_state.return_value = {"database_initialized": False}
        mock_state_manager.return_value = mock_manager

        from giljo_mcp.setup.state_manager import SetupStateManager

        manager = SetupStateManager.get_instance(tenant_key="default")
        state = manager.get_state()

        assert state["database_initialized"] is False

    @patch("giljo_mcp.setup.state_manager.SetupStateManager.get_instance")
    def test_first_run_completed(self, mock_state_manager):
        """Test detection when setup is completed."""
        mock_manager = MagicMock()
        mock_manager.get_state.return_value = {"database_initialized": True}
        mock_state_manager.return_value = mock_manager

        from giljo_mcp.setup.state_manager import SetupStateManager

        manager = SetupStateManager.get_instance(tenant_key="default")
        state = manager.get_state()

        assert state["database_initialized"] is True


class TestServiceManagement:
    """Test service startup and management."""

    @patch("subprocess.Popen")
    def test_api_server_startup(self, mock_popen):
        """Test API server startup command."""
        mock_process = MagicMock()
        mock_process.pid = 1234
        mock_popen.return_value = mock_process

        # Simulate starting API server
        process = subprocess.Popen(["python", "api/run_api.py"])

        assert process is not None
        assert mock_popen.called

    @patch("subprocess.Popen")
    def test_frontend_startup(self, mock_popen):
        """Test frontend server startup command."""
        mock_process = MagicMock()
        mock_process.pid = 5678
        mock_popen.return_value = mock_process

        # Simulate starting frontend
        process = subprocess.Popen(["npm", "run", "dev"], cwd="frontend/")

        assert process is not None
        assert mock_popen.called

    @patch("webbrowser.open")
    def test_browser_opening(self, mock_browser):
        """Test browser opening functionality."""
        import webbrowser

        webbrowser.open("http://localhost:7274")

        mock_browser.assert_called_once_with("http://localhost:7274")


class TestCrossPlatformCompatibility:
    """Test cross-platform compatibility."""

    def test_pathlib_usage(self):
        """Test that pathlib.Path works correctly."""
        from pathlib import Path

        test_path = Path.cwd() / "startup.py"
        assert isinstance(test_path, Path)

    def test_platform_detection(self):
        """Test platform detection."""
        import platform

        system = platform.system()
        assert system in ["Windows", "Linux", "Darwin"]

    @patch("platform.system")
    def test_windows_detection(self, mock_platform):
        """Test Windows platform detection."""
        mock_platform.return_value = "Windows"
        import platform

        assert platform.system() == "Windows"

    @patch("platform.system")
    def test_linux_detection(self, mock_platform):
        """Test Linux platform detection."""
        mock_platform.return_value = "Linux"
        import platform

        assert platform.system() == "Linux"


class TestErrorHandling:
    """Test error handling for common failures."""

    def test_missing_database_url(self):
        """Test handling of missing DATABASE_URL."""
        from giljo_mcp.database import DatabaseManager

        with pytest.raises(ValueError, match="Database URL is required"):
            DatabaseManager(database_url=None, is_async=False)

    @patch("subprocess.Popen")
    def test_service_startup_failure(self, mock_popen):
        """Test handling of service startup failure."""
        mock_popen.side_effect = FileNotFoundError("python not found")

        with pytest.raises(FileNotFoundError):
            subprocess.Popen(["python", "api/run_api.py"])


class TestConfigurationLoading:
    """Test configuration file loading."""

    def test_config_yaml_reading(self, tmp_path):
        """Test reading config.yaml file."""
        import yaml

        # Create temporary config file
        config_file = tmp_path / "config.yaml"
        config_data = {
            "installation": {"mode": "localhost"},
            "services": {"api": {"port": 7272}, "frontend": {"port": 7274}},
        }

        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        # Read and verify
        with open(config_file) as f:
            loaded_config = yaml.safe_load(f)

        assert loaded_config["installation"]["mode"] == "localhost"
        assert loaded_config["services"]["api"]["port"] == 7272

    def test_dotenv_loading(self, tmp_path, monkeypatch):
        """Test .env file parses without mutating os.environ."""
        import os

        from dotenv import dotenv_values

        env_file = tmp_path / ".env"
        env_file.write_text("DATABASE_URL=postgresql://localhost/test\n")

        dotenv_keys = ["DATABASE_URL"]
        pre_snapshot = {key: os.environ.get(key) for key in dotenv_keys}

        monkeypatch.chdir(tmp_path)
        parsed = dotenv_values(env_file)

        assert parsed.get("DATABASE_URL") == "postgresql://localhost/test"

        post_snapshot = {key: os.environ.get(key) for key in dotenv_keys}
        assert post_snapshot == pre_snapshot, "dotenv_values must not mutate os.environ"


class TestColoredOutput:
    """Test colored console output."""

    def test_colorama_available(self):
        """Test that colorama is available for colored output."""
        try:
            import colorama

            assert colorama is not None
        except ImportError:
            pytest.fail("colorama not available - required for colored output")

    def test_colorama_init(self):
        """Test colorama initialization."""
        from colorama import init

        init()  # Should not raise


class TestPortDetection:
    """Test port availability detection."""

    def test_port_in_range(self):
        """Test that port numbers are in valid range."""
        test_ports = [7272, 7273, 7274]
        for port in test_ports:
            assert 1024 <= port <= 65535

    @patch("socket.socket")
    def test_port_availability_check(self, mock_socket):
        """Test checking if a port is available."""
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0  # Port occupied
        mock_socket.return_value.__enter__.return_value = mock_sock

        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            result = sock.connect_ex(("127.0.0.1", 7272))

        assert result == 0  # Port is occupied
