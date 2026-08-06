# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
v3.0 Configuration file generation for .env and config.yaml
Bind address derived from install-time network choice (localhost=127.0.0.1, LAN/WAN/custom=0.0.0.0).
Install always configures plain HTTP (ssl_enabled=False); HTTPS is an opt-in bring-your-own-cert
toggle in Settings -> Network.
Authentication always enabled with IP-based auto-login for localhost
"""

import logging
import os
import platform
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


class ConfigManager:
    """
    Generate and manage configuration files for v3.0 unified architecture.

    Key v3.0 principles:
    - No deployment modes (local/server/lan/wan)
    - Bind address derived from install-time network choice (localhost=127.0.0.1, LAN/WAN/custom=0.0.0.0).
      Install always configures plain HTTP (ssl_enabled=False); HTTPS is an opt-in
      bring-your-own-cert toggle in Settings -> Network.
    - Database always on localhost (security principle)
    - Authentication always enabled (IP-based auto-login for 127.0.0.1)
    - deployment_context is metadata only (not a mode)
    """

    def __init__(self, settings: Dict[str, Any]):
        self.settings = settings
        self.logger = logging.getLogger(self.__class__.__name__)

        # FIX: Use install_dir from settings for test isolation (prevents tests from overwriting production files)
        # Tests pass install_dir in mock_settings pointing to temp directory
        # Production uses current working directory as default
        install_dir = Path(settings.get("install_dir", Path.cwd()))
        self.config_file = install_dir / "config.yaml"
        self.env_file = install_dir / ".env"

    def generate_all(self) -> Dict[str, Any]:
        """
        Generate all configuration files for v3.0 unified architecture.

        Returns:
            Result dict with success status and any errors
        """
        result = {"success": False, "errors": []}

        try:
            # Generate .env file
            self.logger.info("Generating .env file...")
            env_result = self.generate_env_file()
            if not env_result["success"]:
                result["errors"].extend(env_result.get("errors", []))
                return result

            # Generate config.yaml
            self.logger.info("Generating config.yaml...")
            yaml_result = self.generate_config_yaml()
            if not yaml_result["success"]:
                result["errors"].extend(yaml_result.get("errors", []))
                return result

            result["success"] = True
            self.logger.info("All configuration files generated successfully")
            return result

        except Exception as e:
            result["errors"].append(str(e))
            self.logger.error(f"Configuration generation failed: {e}")
            return result

    def generate_env(self) -> Dict[str, Any]:
        """Alias for generate_env_file for testing compatibility"""
        return self.generate_env_file()

    def _read_latest_credentials(self) -> Optional[Dict[str, str]]:
        """
        Read the most recent database credentials file.

        Returns:
            Dictionary with credential keys and values, or None if not found
        """
        try:
            credentials_dir = Path("installer/credentials")

            if not credentials_dir.exists():
                self.logger.warning(f"Credentials directory not found: {credentials_dir}")
                return None

            # Look for the standard credential file first
            credential_file = credentials_dir / "db_credentials.txt"

            if not credential_file.exists():
                # Fallback: check for legacy timestamped files
                legacy_files = list(credentials_dir.glob("db_credentials_*.txt"))
                if legacy_files:
                    credential_file = max(legacy_files, key=lambda p: p.stat().st_mtime)
                    self.logger.info(f"Using legacy credential file: {credential_file}")
                else:
                    self.logger.warning("No credential files found in installer/credentials/")
                    return None

            latest_file = credential_file
            self.logger.info(f"Reading credentials from: {latest_file}")

            # Parse the credentials file
            credentials = {}
            with open(latest_file, "r") as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith("#"):
                        continue
                    # Parse key=value pairs
                    if "=" in line:
                        key, value = line.split("=", 1)
                        credentials[key.strip()] = value.strip()

            return credentials

        except Exception as e:
            self.logger.error(f"Failed to read credentials file: {e}")
            return None

    def generate_config(self) -> Dict[str, Any]:
        """Alias for generate_config_yaml for testing compatibility"""
        return self.generate_config_yaml()

    def generate_env_file(self) -> Dict[str, Any]:
        """
        Generate .env file for v3.0 unified architecture.

        v3.0 changes:
        - Bind address derived from install-time network choice (localhost=127.0.0.1, LAN/WAN/custom=0.0.0.0);
          install always configures plain HTTP (ssl_enabled=False)
        - DEPLOYMENT_CONTEXT is metadata only
        - Authentication always enabled

        Returns:
            Result dict with success status and any errors
        """
        result = {"success": False, "errors": []}

        try:
            # Get database credentials - try multiple sources
            owner_password = None
            user_password = None

            # Source 1: From settings (if passed from DatabaseInstaller)
            if "owner_password" in self.settings and "user_password" in self.settings:
                owner_password = self.settings.get("owner_password")
                user_password = self.settings.get("user_password")
                self.logger.info("Using database passwords from settings")

            # Source 2: Read from most recent credentials file
            if not owner_password or not user_password:
                credentials = self._read_latest_credentials()
                if credentials:
                    owner_password = credentials.get("OWNER_PASSWORD")
                    user_password = credentials.get("USER_PASSWORD")
                    self.logger.info("Using database passwords from credentials file")

            # Source 3: Raise error if password missing (production security)
            if not owner_password:
                raise ValueError("Owner password is required - no defaults allowed for production security")
            if not user_password:
                raise ValueError("User password is required - no defaults allowed for production security")

            # Get configuration values with correct defaults
            pg_host = self.settings.get("pg_host", "localhost")  # ALWAYS localhost
            pg_port = self.settings.get("pg_port", 5432)
            db_name = self.settings.get("db_name", "giljo_mcp")
            api_port = self.settings.get("api_port", 7272)
            frontend_port = self.settings.get("dashboard_port", 7274)

            # Idempotency (INF-5089): preserve security-sensitive secrets already
            # present in an existing .env. Regenerating .env (e.g. a --repair re-run)
            # must NOT rotate the JWT/session/API secrets out from under a live install
            # - doing so would invalidate every session and stored API key. Only mint
            # fresh secrets when the key is absent.
            existing_secrets: Dict[str, str] = {}
            if self.env_file.exists():
                try:
                    from dotenv import dotenv_values

                    for _k, _v in dotenv_values(str(self.env_file)).items():
                        if _v:
                            existing_secrets[_k] = _v
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.warning(f"Could not read existing .env for secret preservation: {exc}")
                    existing_secrets = {}

            def _secret(key: str) -> str:
                """Reuse an existing secret if present, else mint a fresh one."""
                return existing_secrets.get(key) or self.generate_secret_key()

            # Bind address derived from install-time network choice (localhost=127.0.0.1, LAN/WAN/custom=0.0.0.0); plain HTTP always
            bind_address = self.settings.get("bind", "127.0.0.1")
            api_url_host = self.settings.get("external_host", "localhost")
            network_mode = self.settings.get("network_mode", "localhost")
            ssl_enabled = self.settings.get("ssl_enabled", False)
            http_proto = "https" if ssl_enabled else "http"
            ws_proto = "wss" if ssl_enabled else "ws"

            # Frontend URL resolution (ADR-001): the installed FastAPI server serves
            # the dashboard AND the API from the same origin, so for any non-localhost
            # install we leave VITE_API_URL/VITE_WS_URL EMPTY and let the resolver
            # (useApiUrl.js getApiBaseUrl) fall through to window.location.origin.
            # That is immune to host/scheme drift - the LAN/HTTPS bug was emitting an
            # absolute http://localhost URL onto an https://<lan-ip> page. Only a
            # genuinely different-origin deployment (e.g. Cloudflare-tunnel demo) sets
            # VITE_API_URL explicitly via its own env. localhost installs keep the
            # explicit absolute URL (unchanged behaviour).
            is_localhost_install = network_mode == "localhost" and api_url_host in (
                "localhost",
                "127.0.0.1",
            )
            vite_api_url = f"{http_proto}://{api_url_host}:{api_port}" if is_localhost_install else ""
            vite_ws_url = f"{ws_proto}://{api_url_host}:{api_port}" if is_localhost_install else ""

            # ENVIRONMENT follows the installer's frontend-mode choice (INF-9155): a
            # Production install stamps ENVIRONMENT=production; the Contributor/Dev path
            # (and any first write before the choice is made) stays development so
            # is_development_mode()'s frontend/dist signal keeps the Vite HMR relaxation.
            frontend_mode = str(self.settings.get("frontend_mode", "development")).lower()
            environment = "production" if frontend_mode == "production" else "development"

            env_content = f"""# Giljo HQ Environment Configuration v3.0
# Generated: {datetime.now().isoformat()}
# Deployment Context: {network_mode} (informational only - not a mode)

# =============================================================================
# PORT CONFIGURATION (v2.0+ Unified Architecture)
# =============================================================================
# Main API Server Port (handles API + WebSocket + MCP tools)
GILJO_API_PORT={api_port}
GILJO_PORT={api_port}

# Frontend Development Server Port
GILJO_FRONTEND_PORT={frontend_port}
VITE_FRONTEND_PORT={frontend_port}

# PostgreSQL Database Port
POSTGRES_PORT={pg_port}
DB_PORT={pg_port}

# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================
# PostgreSQL specific configuration
POSTGRES_HOST={pg_host}
POSTGRES_DB={db_name}
POSTGRES_USER=giljo_user
POSTGRES_PASSWORD={user_password}

# Database Owner (for migrations only)
POSTGRES_OWNER_USER=giljo_owner
POSTGRES_OWNER_PASSWORD={owner_password}

# PostgreSQL superuser password (for database management tools)
PG_SUPERUSER_PASSWORD={self.settings.get("pg_password", "")}

# Generic database configuration (for application compatibility)
DB_TYPE=postgresql
DB_HOST={pg_host}
DB_NAME={db_name}
DB_USER=giljo_user
DB_PASSWORD={user_password}

# Full database URL (optional - app will use this if present)
DATABASE_URL=postgresql://giljo_user:{user_password}@{pg_host}:{pg_port}/{db_name}

# =============================================================================
# SERVER CONFIGURATION (v3.0)
# =============================================================================
# Deployment context (informational only - not a mode)
DEPLOYMENT_CONTEXT={network_mode}

# API Host (bind address derived from install-time network choice)
GILJO_API_HOST={bind_address}
SERVICE_BIND={bind_address}

# Public URL for MCP tool download links (agents use this to reach the server)
GILJO_PUBLIC_URL={http_proto}://{api_url_host}:{api_port}

# =============================================================================
# FRONTEND CONFIGURATION
# =============================================================================
# API URL for frontend. Empty for non-localhost installs -> resolver uses
# same-origin window.location.origin (ADR-001). Set only for different-origin
# deployments (e.g. Cloudflare-tunnel demo).
VITE_API_URL={vite_api_url}
VITE_WS_URL={vite_ws_url}
VITE_APP_MODE={network_mode}
VITE_API_PORT={api_port}

# =============================================================================
# ENVIRONMENT SETTINGS
# =============================================================================
ENVIRONMENT={environment}
DEBUG=true
LOG_LEVEL=DEBUG
LOG_FILE=./logs/giljo_mcp.log

# =============================================================================
# SECURITY (v3.0: Authentication always enabled)
# =============================================================================
# API Key for network clients (optional - generated at runtime if needed)
GILJO_MCP_API_KEY={existing_secrets.get("GILJO_MCP_API_KEY", "")}

# Default tenant key (generated during installation for admin user)
DEFAULT_TENANT_KEY={self.settings.get("default_tenant_key") or existing_secrets.get("DEFAULT_TENANT_KEY", "")}

# Secret keys for session management
GILJO_MCP_SECRET_KEY={_secret("GILJO_MCP_SECRET_KEY")}
SECRET_KEY={_secret("SECRET_KEY")}
JWT_SECRET={_secret("JWT_SECRET")}
SESSION_SECRET={_secret("SESSION_SECRET")}

# =============================================================================
# CORS CONFIGURATION
# =============================================================================
CORS_ORIGINS=http://localhost:7274,http://127.0.0.1:7274,http://localhost:7272,http://127.0.0.1:7272

# =============================================================================
# FEATURE FLAGS (v3.0: Core features always enabled)
# =============================================================================
# BE-9148 + BE-9138: retired the dead feature-flag/agent/session-timeout vars that
# had zero consumers (ENABLE_VISION_CHUNKING/AUTO_HANDOFF/DYNAMIC_DISCOVERY/
# AUTHENTICATION/AUTO_LOGIN_LOCALHOST/API_KEYS/MULTI_USER/MULTI_TENANT/WEBSOCKET,
# MAX_AGENTS_PER_PROJECT, AGENT_CONTEXT_LIMIT, AGENT_HANDOFF_THRESHOLD, SESSION_TIMEOUT).
# An existing .env that still sets them is tolerated - nothing reads them.

# =============================================================================
# SESSION CONFIGURATION
# =============================================================================
MAX_CONCURRENT_SESSIONS=10
SESSION_CLEANUP_INTERVAL=300

# =============================================================================
# MESSAGE QUEUE CONFIGURATION
# =============================================================================
MAX_QUEUE_SIZE=1000
MESSAGE_BATCH_SIZE=10
MESSAGE_RETRY_ATTEMPTS=3
MESSAGE_RETRY_DELAY=1.0

# =============================================================================
# PATHS
# =============================================================================
DATA_DIR=./data
LOGS_DIR=./logs
UPLOAD_DIR=./uploads
TEMP_DIR=./temp

# =============================================================================
# PERFORMANCE
# =============================================================================
WORKER_COUNT=1
CONNECTION_POOL_SIZE=5

# =============================================================================
# DOCKER BUILD CONFIGURATION
# =============================================================================
BUILD_TARGET=development

# =============================================================================
# ACTIVE PRODUCT
# =============================================================================
ACTIVE_PRODUCT=GiljoAI-MCP Coding Orchestrator
"""

            # Write .env file (use configured path)
            self.env_file.write_text(env_content, encoding="utf-8")

            # Set restrictive permissions on Unix
            if platform.system() != "Windows":
                os.chmod(self.env_file, 0o600)

            result["success"] = True
            result["path"] = str(self.env_file.absolute())
            self.logger.info(f"Created .env file: {self.env_file.absolute()}")

            # Fixed: Return the result dictionary, not the path string
            return result

        except Exception as e:
            result["errors"].append(str(e))
            self.logger.error(f"Failed to generate .env: {e}")
            return result

    def generate_config_yaml(self) -> Dict[str, Any]:
        """
        Generate config.yaml for v3.0 unified architecture.

        v3.0 changes:
        - No mode field anywhere
        - deployment_context is metadata only
        - Bind address derived from install-time network choice (localhost=127.0.0.1, LAN/WAN/custom=0.0.0.0);
          install always configures plain HTTP (ssl_enabled=False)
        - Database always on localhost
        - Authentication always enabled

        Returns:
            Result dict with success status and any errors
        """
        result = {"success": False, "errors": []}

        try:
            # Get correct port values
            api_port = self.settings.get("api_port", 7272)
            frontend_port = self.settings.get("dashboard_port", 7274)

            # Get install directory
            install_dir = self.settings.get("install_dir", str(Path.cwd()))

            # Bind address: localhost=127.0.0.1 (safe), LAN/WAN=0.0.0.0 (exposed)
            bind_address = self.settings.get("bind", "127.0.0.1")

            # network_mode drives deployment_context so LAN/WAN installs don't
            # write "localhost" here and confuse get_deployment_context() at runtime.
            network_mode = self.settings.get("network_mode", "localhost")

            config = {
                "version": "3.0.0",  # v3.0: Unified authentication architecture
                "deployment_context": network_mode,  # Informational only (not a mode)
                "installation": {
                    # NO MODE FIELD in v3.0
                    "timestamp": datetime.now().isoformat(),
                    "platform": platform.system(),
                    "python_version": platform.python_version(),
                    "install_dir": install_dir,
                },
                "database": {
                    "type": "postgresql",
                    "version": "18",  # PostgreSQL 18
                    # CRITICAL: Database host is ALWAYS localhost (security principle)
                    # The database is co-located with the backend and NEVER exposed to network
                    # Only the API layer is network-accessible (bind address from install-time network choice)
                    "host": "localhost",  # ALWAYS localhost (never changes)
                    "port": self.settings.get("pg_port", 5432),
                    "name": self.settings.get("db_name", "giljo_mcp"),
                    "user": "giljo_user",
                    "owner": "giljo_owner",
                    "pool_size": 5,  # v3.0: Fixed pool size (no mode-based scaling)
                    # PostgreSQL installation paths (discovered during install)
                    "postgresql": {
                        "installation_path": self.settings.get("postgresql_installation_path"),
                        "bin_path": self.settings.get("postgresql_bin_path"),
                        "psql_executable": self.settings.get("postgresql_psql_path"),
                        "discovered_at": self.settings.get("postgresql_discovered_at"),
                        "custom_path": self.settings.get("postgresql_custom_path", False),
                        "discovery_method": self.settings.get("postgresql_discovery_method", "auto"),
                    }
                    if self.settings.get("postgresql_bin_path")
                    else {},
                },
                "server": {
                    # Bind address derived from install-time network choice
                    # (localhost=127.0.0.1, LAN/WAN/custom=0.0.0.0; plain HTTP; HTTPS is opt-in via Settings -> Network)
                    "api_host": bind_address,
                    "api_port": api_port,
                    "dashboard_host": bind_address,
                    "dashboard_port": frontend_port,
                    "mcp_host": bind_address,
                    "mcp_port": api_port,  # MCP uses same port as API in v2.0+
                    "api_key": None,  # Generated on first run if needed
                },
                "services": {
                    "api": {
                        "host": bind_address,  # Bind address derived from install-time network choice
                        "port": api_port,
                        "unified_port": True,  # v2.0 uses single port for API+WebSocket
                        "description": "Main API server (REST + WebSocket + MCP)",
                    },
                    "frontend": {
                        "port": frontend_port,
                        "dev_server": True,
                        "auto_open": self.settings.get("open_browser", True),
                    },
                    "external_host": self.settings.get("external_host", "localhost"),  # Host for frontend connections
                },
                "features": {
                    # v3.0 feature flags
                    "authentication": True,  # Always enabled in v3.0
                    "auto_login_localhost": True,  # IP-based auto-login for 127.0.0.1
                    "firewall_configured": self.settings.get("configure_firewall", False),
                    # Security features (optional)
                    "ssl_enabled": self.settings.get("ssl_enabled", False),
                },
                "paths": {
                    "install_dir": install_dir,
                    "data": str(Path(install_dir) / "data"),
                    "logs": str(Path(install_dir) / "logs"),
                    "uploads": str(Path(install_dir) / "uploads"),
                    "temp": str(Path(install_dir) / "temp"),
                    "static": str(Path(install_dir) / "frontend" / "dist"),
                    "templates": str(Path(install_dir) / "frontend" / "templates"),
                    "certs": str(Path(install_dir) / "certs") if self.settings.get("ssl_enabled") else None,
                    "ssl_cert": self.settings.get("ssl_cert"),
                    "ssl_key": self.settings.get("ssl_key"),
                },
                "logging": {
                    "level": "DEBUG",  # v3.0: Default to DEBUG for localhost
                    "file": "./logs/giljo_mcp.log",
                    "max_size": "10MB",
                    "backup_count": 5,
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                },
                "agent": {
                    "max_agents": 20,
                    "default_context_budget": 150000,
                    "context_warning_threshold": 140000,
                    "default_role": "orchestrator",
                },
                "session": {
                    "timeout_seconds": 3600,
                    "max_concurrent": 10,
                    "cleanup_interval": 300,
                    "cookie_secure": False,  # v3.0: Set to False for localhost
                },
                "message_queue": {
                    "max_size": 1000,
                    "batch_size": 10,
                    "max_retries": 3,
                    "retry_delay": 1.0,
                    "priority_levels": ["low", "normal", "high", "critical"],
                },
                "status": {
                    "installation_complete": True,
                    "database_created": True,
                    "migrations_run": False,  # Will be updated after migrations
                    "services_configured": True,
                    "ready_to_launch": True,
                },
            }

            # Add tenant configuration (tenant key from installation)
            tenant_key = self.settings.get("default_tenant_key", "")
            if tenant_key:
                config["tenant"] = {
                    "enabled": True,
                    "default_key": tenant_key,
                    "key_header": "X-Tenant-Key",
                }

            # Add security configuration (v3.0: Always included, no mode dependency)
            config["security"] = self._generate_security_config()

            # Write config.yaml (use configured path)
            with open(self.config_file, "w", encoding="utf-8") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

            result["success"] = True
            result["path"] = str(self.config_file.absolute())
            self.logger.info(f"Created config.yaml: {self.config_file.absolute()}")

            # Fixed: Return the result dictionary, not the path string
            return result

        except Exception as e:
            result["errors"].append(str(e))
            self.logger.error(f"Failed to generate config.yaml: {e}")
            return result

    def _generate_security_config(self) -> Dict[str, Any]:
        """
        Generate security configuration for v3.0 unified architecture.

        v3.0 changes:
        - No mode-based branching
        - CORS defaults to localhost only
        - API keys optional (generated at runtime if needed)

        Returns:
            Security configuration dictionary with CORS, API keys, and rate limiting
        """
        import re

        # Get API and frontend ports
        api_port = self.settings.get("api_port", 7272)
        frontend_port = self.settings.get("dashboard_port", 7274)

        # v3.0: Default CORS to localhost only (firewall controls network access)
        cors_origins = [
            f"http://127.0.0.1:{frontend_port}",
            f"http://localhost:{frontend_port}",
            f"http://127.0.0.1:{api_port}",
            f"http://localhost:{api_port}",
        ]

        # Include installer-selected external host (LAN/WAN) for direct access
        external_host = self.settings.get("external_host", "localhost")
        if external_host and external_host not in ("localhost", "127.0.0.1"):
            external_frontend = f"http://{external_host}:{frontend_port}"
            external_api = f"http://{external_host}:{api_port}"
            if external_frontend not in cors_origins:
                cors_origins.append(external_frontend)
            if external_api not in cors_origins:
                cors_origins.append(external_api)

        # Add custom origins if provided (advanced users)
        custom_origins = self.settings.get("cors_origins", [])
        if custom_origins:
            cors_origins.extend(custom_origins)

        # Build cookie_domains whitelist for cross-port authentication
        # Only include domain names (not IPs - they're auto-allowed by FastAPI)
        cookie_domains = []
        ip_pattern = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")

        # Check custom_domain from installer prompt
        custom_domain = self.settings.get("custom_domain")
        if custom_domain and not ip_pattern.match(custom_domain):
            cookie_domains.append(custom_domain)

        # Check external_host if it's a domain name (not IP, not localhost)
        if external_host and external_host not in ("localhost", "127.0.0.1"):
            if not ip_pattern.match(external_host) and external_host not in cookie_domains:
                cookie_domains.append(external_host)

        security_config = {
            "cors": {
                "allowed_origins": cors_origins
                # Note: Do NOT use wildcards like 'http://192.0.2.*:7274' - they don't work
                # Add specific IPs instead: 'http://192.0.2.10:7274'
            },
            "cookie_domains": cookie_domains,  # Whitelist for cookie domain setting (cross-port auth)
            "api_keys": {
                # API keys documentation (not enforced in v3.0 localhost mode)
                "info": "API keys optional for localhost (auto-login enabled)",
                "generate_command": "python -c \"import secrets; print(f'giljo_{secrets.token_urlsafe(32)}')\"",
            },
            "rate_limiting": {
                "enabled": True,
                "requests_per_minute": 60,
                # Adjust per-endpoint limits in api/middleware.py if needed
            },
        }

        # Add network adapter tracking for dynamic IP detection (v3.1+)
        # This enables CORS updates when network adapter IP changes between sessions
        network_mode = self.settings.get("network_mode", "localhost")
        security_config["network"] = {
            "mode": network_mode,  # auto, static, localhost, or custom
        }

        # Include adapter info for auto/static modes (enables dynamic detection)
        if network_mode in ("auto", "static"):
            selected_adapter = self.settings.get("selected_adapter")
            initial_ip = self.settings.get("initial_ip")
            if selected_adapter and initial_ip:
                security_config["network"]["selected_adapter"] = selected_adapter
                security_config["network"]["initial_ip"] = initial_ip

        return security_config

    def generate_secret_key(self, length: int = 32) -> str:
        """Generate a secure random secret key"""
        import secrets

        return secrets.token_urlsafe(length)

    def validate_config(self) -> Dict[str, Any]:
        """Validate that generated configuration is compatible with application"""
        result = {"valid": True, "issues": []}

        # Check .env file
        if self.env_file.exists():
            env_content = self.env_file.read_text(encoding="utf-8")

            # Check for required variables
            required_vars = [
                "GILJO_API_PORT",
                "GILJO_PORT",
                "DB_HOST",
                "DB_NAME",
                "DB_USER",
                "DB_PASSWORD",
                "VITE_API_URL",
                "VITE_WS_URL",
            ]

            for var in required_vars:
                if f"{var}=" not in env_content:
                    result["valid"] = False
                    result["issues"].append(f"Missing required variable: {var}")
        else:
            result["valid"] = False
            result["issues"].append(".env file not found")

        # Check config.yaml
        if self.config_file.exists():
            with open(self.config_file, "r") as f:
                config = yaml.safe_load(f)

            # Validate structure
            if "services" not in config:
                result["valid"] = False
                result["issues"].append("Missing 'services' section in config.yaml")

            if "database" not in config:
                result["valid"] = False
                result["issues"].append("Missing 'database' section in config.yaml")
        else:
            result["valid"] = False
            result["issues"].append("config.yaml file not found")

        return result
