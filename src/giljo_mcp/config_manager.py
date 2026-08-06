# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Enhanced Configuration Manager for Giljo HQ.

This module provides a robust configuration system that:
- Loads configuration from YAML files
- Supports environment variable overrides
- Implements mode detection (local/LAN/WAN)
- Validates configuration on load
- Provides smart defaults
- Supports hot-reloading of configuration
"""

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

# Import from centralized exceptions
from .branding import PRODUCT_NAME
from .exceptions import ConfigValidationError


logger = logging.getLogger(__name__)


# DeploymentMode enum removed in v3.0
# Localhost installs bind 127.0.0.1 (HTTP). LAN/WAN installs bind 0.0.0.0 over plain HTTP;
# HTTPS is an opt-in bring-your-own-cert toggle (Settings -> Network).
# Bind address derived from install-time network choice. Authentication always enabled.


@dataclass
class ServerConfig:
    """Server configuration settings.

    Localhost installs bind 127.0.0.1 (HTTP). LAN/WAN installs bind 0.0.0.0
    over plain HTTP; HTTPS is an opt-in bring-your-own-cert toggle (Settings -> Network).
    Bind address derived from install-time network choice.
    Access control is handled via:
    - IP-based auto-login for localhost
    - API key for network clients
    """

    # MCP Server - bind address set by installer (127.0.0.1 or 0.0.0.0)
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 6001
    mcp_transport: str = "http"

    # REST API - bind address set by installer (127.0.0.1 or 0.0.0.0)
    api_host: str = "0.0.0.0"
    api_port: int = 7272  # Production default (PortManager managed)
    api_cors_enabled: bool = True
    api_key: str | None = None  # Generated on first run

    # WebSocket
    websocket_enabled: bool = True
    websocket_port: int = 6003

    # Dashboard - bind address set by installer (127.0.0.1 or 0.0.0.0)
    dashboard_enabled: bool = True
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 7274
    dashboard_dev_port: int = 5173


@dataclass
class DatabaseConfig:
    """Database configuration settings."""

    type: str = "postgresql"  # PostgreSQL only
    database_name: str = "giljo_mcp.db"
    database_url: str | None = None

    # PostgreSQL settings
    host: str = "localhost"
    port: int = 5432
    username: str = "postgres"
    password: str = ""
    # INF-3009a: the authoritative per-worker DB pool knob. pg_pool_size +
    # pg_max_overflow are wired straight into DatabaseManager (no more psutil
    # host-RAM heuristic). pg_slot_budget is the deployment-wide connection
    # ceiling the startup sanity check compares workers x (pool+overflow) against.
    pg_pool_size: int = 10
    pg_max_overflow: int = 10
    pg_slot_budget: int = 90

    def get_connection_string(self, tenant_key: str | None = None) -> str:
        """
        Generate database connection string.

        Args:
            tenant_key: Optional tenant key for multi-tenant database separation
        """
        if self.database_url:
            return self.database_url

        if self.type == "postgresql":
            # Try to use DatabaseManager's method if available
            try:
                from giljo_mcp.database import DatabaseManager

                return DatabaseManager.build_postgresql_url(
                    host=self.host,
                    port=self.port,
                    database=(self.database_name if not tenant_key else f"{self.database_name}_{tenant_key}"),
                    username=self.username,
                    password=self.password or os.getenv("DB_PASSWORD", ""),
                )
            except ImportError:
                # Fallback to manual URL building
                password = self.password or os.getenv("DB_PASSWORD", "")
                base_url = f"postgresql://{self.username}:{password}@{self.host}:{self.port}"

                # Support tenant-specific schemas in PostgreSQL if multi-tenant enabled
                if tenant_key:
                    # Use database name with tenant suffix for complete isolation
                    return f"{base_url}/{self.database_name}_{tenant_key}"
                return f"{base_url}/{self.database_name}"
        else:
            raise ValueError(f"Unsupported database type: {self.type}")


@dataclass
class LoggingConfig:
    """Logging configuration settings."""

    level: str = "INFO"
    file: Path = field(default_factory=lambda: Path("./logs/giljo_mcp.log"))
    max_size: str = "10MB"
    max_files: int = 5

    def setup_logging(self):
        """Configure logging based on settings."""
        self.file.parent.mkdir(parents=True, exist_ok=True)

        log_level = getattr(logging, self.level.upper(), logging.INFO)

        # Configure file handler with rotation
        from giljo_mcp.logging import _SafeRotatingFileHandler

        # Parse max_size (e.g., "10MB" -> 10485760)
        size_str = self.max_size.upper()
        if size_str.endswith("MB"):
            max_bytes = int(size_str[:-2]) * 1024 * 1024
        elif size_str.endswith("KB"):
            max_bytes = int(size_str[:-2]) * 1024
        else:
            max_bytes = int(size_str)

        handler = _SafeRotatingFileHandler(self.file, maxBytes=max_bytes, backupCount=self.max_files)

        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)

        logging.basicConfig(level=log_level, handlers=[handler, logging.StreamHandler()])


@dataclass
class SessionConfig:
    """Session configuration settings."""

    timeout: int = 3600  # seconds
    max_concurrent: int = 10
    cleanup_interval: int = 300  # seconds


@dataclass
class AgentConfig:
    """Agent configuration settings."""

    max_agents: int = 20  # tokens


@dataclass
class MessageConfig:
    """Message queue configuration settings."""

    max_queue_size: int = 1000
    message_timeout: int = 300  # seconds
    max_retries: int = 3
    batch_size: int = 10
    retry_delay: float = 1.0  # seconds


@dataclass
class UploadConfig:
    """File upload guardrails (SEC-0001 Phase 2).

    Governs the vision-document upload endpoints. Two layers of size
    enforcement live in the endpoints (Content-Length pre-check + streaming
    byte counter); both read ``max_upload_bytes`` from here. The allowlist
    and sniff window are exposed for test overrides and future tuning.
    """

    #: Hard cap on upload body size in bytes. 5 MiB.
    max_upload_bytes: int = 5_242_880
    #: Extensions accepted by both upload endpoints. Kept in sync with
    #: ``giljo_mcp.security.upload_guard.TEXT_EXTENSIONS``.
    allowed_extensions: tuple[str, ...] = (".txt", ".md", ".markdown")
    #: Byte-sniff window size for text-content detection.
    sniff_bytes: int = 8192


@dataclass
class TenantConfig:
    """Multi-tenant configuration settings."""

    enable_multi_tenant: bool = True
    default_tenant_key: str | None = None
    tenant_isolation_level: str = "strict"
    key_header: str = "X-Tenant-Key"


class ConfigFileWatcher(FileSystemEventHandler):
    """Watch config file for changes and trigger reload."""

    def __init__(self, config_manager: "ConfigManager"):
        self.config_manager = config_manager

    def on_modified(self, event: FileModifiedEvent):
        if not event.is_directory and event.src_path.endswith(".yaml"):
            logger.info(f"Config file changed: {event.src_path}")
            self.config_manager.reload()


class ConfigManager:
    """
    Central configuration management for Giljo HQ.

    Features:
    - Hierarchical configuration (defaults -> file -> env vars)
    - Mode detection and automatic adjustment
    - Configuration validation
    - Hot-reloading support
    - Thread-safe operations
    """

    def __init__(self, config_path: Path | None = None, auto_reload: bool = False):
        """
        Initialize ConfigManager.

        Args:
            config_path: Path to configuration file
            auto_reload: Enable hot-reloading of config file
        """
        self.config_path = config_path or Path("./config.yaml")
        self.auto_reload = auto_reload
        self._lock = threading.RLock()
        self._observer = None

        # Initialize configurations
        self.server = ServerConfig()
        self.database = DatabaseConfig()
        self.logging = LoggingConfig()
        self.session = SessionConfig()
        self.agent = AgentConfig()
        self.message = MessageConfig()
        self.upload = UploadConfig()
        self.tenant = TenantConfig()

        # Application metadata (restored from cleanup)
        self.app_name = PRODUCT_NAME
        self.app_version = "1.0.0"

        # Raw config dict cache (populated by _load_from_file, used by get_nested)
        self._raw_config: dict = {}

        # Setup mode flag (allows placeholder passwords during wizard)
        self.setup_mode = False

        # Load configuration
        self.load()

        # Setup hot-reloading if enabled
        if auto_reload:
            self._setup_file_watcher()

    # deployment_mode property removed in v3.0
    # No longer needed as mode detection is removed

    def load(self):
        """Load configuration from file and environment variables."""
        with self._lock:
            # 1. Load from YAML file
            if self.config_path.exists():
                self._load_from_file()

            # 2. Override with environment variables
            self._load_from_env()

            # 3. Validate configuration
            self.validate()

            logger.info("Configuration loaded successfully (v3.0 - mode detection removed)")

    def _migrate_v2_config(self, data: dict) -> dict:
        """Migrate v2.x config to v3.0 format.

        Args:
            data: Configuration dictionary from YAML

        Returns:
            Migrated configuration dictionary
        """
        if "version" in data and data.get("version", "").startswith("3."):
            return data  # Already v3

        logger.info("Migrating v2.x config to v3.0 format")

        # Detect old mode
        old_mode = data.get("server", {}).get("mode", "local")
        if "installation" in data and "mode" in data["installation"]:
            old_mode = data["installation"]["mode"]

        # Remove mode field from server section
        if "server" in data and "mode" in data["server"]:
            del data["server"]["mode"]

        # Remove mode field from installation section
        if "installation" in data and "mode" in data["installation"]:
            del data["installation"]["mode"]

        # Add v3 fields
        data["version"] = "1.0.0"

        # Map old mode to deployment context (informational only).
        # Note: if old_mode was "demo" (retired edition), it is written as-is here.
        # get_deployment_context() will return "demo" for that config, which no
        # longer matches any branch in startup.py and falls through to dashboard
        # or /welcome — harmless. Users should update deployment_context to
        # "localhost" or "lan" manually if they encounter this.
        data["deployment_context"] = old_mode

        # Ensure features section
        if "features" not in data:
            data["features"] = {}

        data["features"]["authentication"] = True
        data["features"]["auto_login_localhost"] = True
        data["features"]["firewall_configured"] = False

        # Ensure host bind address matches install-time network choice
        if "server" not in data:
            data["server"] = {}

        # Update network binding
        if "api" not in data["server"]:
            data["server"]["api"] = {}
        data["server"]["api"]["host"] = "0.0.0.0"

        if "dashboard" not in data["server"]:
            data["server"]["dashboard"] = {}
        data["server"]["dashboard"]["host"] = "0.0.0.0"

        if "mcp" not in data["server"]:
            data["server"]["mcp"] = {}
        data["server"]["mcp"]["host"] = "0.0.0.0"

        logger.info(f"Config migrated from {old_mode} mode to v3.0")

        return data

    def _load_from_file(self):
        """Load configuration from YAML file."""
        try:
            with open(self.config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            # Migrate v2.x config if needed
            data = self._migrate_v2_config(data)

            # Cache the raw config dict for get_nested() access
            self._raw_config = data

            # Warn about deprecated mode field (after migration removes it)
            if "server" in data and "mode" in data["server"]:
                logger.warning(
                    "Deprecated 'mode' field found in config.yaml. "
                    "This field is ignored in v3.0. "
                    "See MIGRATION_GUIDE_V3.md for details."
                )
                del data["server"]["mode"]

            if "installation" in data and "mode" in data["installation"]:
                logger.warning(
                    "Deprecated 'mode' field found in installation section. "
                    "This field is ignored in v3.0. "
                    "See MIGRATION_GUIDE_V3.md for details."
                )
                del data["installation"]["mode"]

            # Server configuration
            if "server" in data:
                srv = data["server"]
                self.server.api_key = srv.get("api_key", self.server.api_key)  # Load API key

                if "mcp" in srv:
                    self.server.mcp_host = srv["mcp"].get("host", self.server.mcp_host)
                    self.server.mcp_port = srv["mcp"].get("port", self.server.mcp_port)
                    self.server.mcp_transport = srv["mcp"].get("transport", self.server.mcp_transport)

                if "api" in srv:
                    self.server.api_host = srv["api"].get("host", self.server.api_host)
                    self.server.api_port = srv["api"].get("port", self.server.api_port)
                    self.server.api_cors_enabled = srv["api"].get("cors_enabled", self.server.api_cors_enabled)

                if "websocket" in srv:
                    self.server.websocket_enabled = srv["websocket"].get("enabled", self.server.websocket_enabled)
                    self.server.websocket_port = srv["websocket"].get("port", self.server.websocket_port)

                if "dashboard" in srv:
                    self.server.dashboard_enabled = srv["dashboard"].get("enabled", self.server.dashboard_enabled)
                    self.server.dashboard_host = srv["dashboard"].get("host", self.server.dashboard_host)
                    self.server.dashboard_port = srv["dashboard"].get("port", self.server.dashboard_port)
                    self.server.dashboard_dev_port = srv["dashboard"].get(
                        "dev_server_port", self.server.dashboard_dev_port
                    )

            # Database configuration
            if "database" in data:
                db = data["database"]
                self.database.type = db.get("type", self.database.type)

                # v3 primary: nested postgresql config
                if "postgresql" in db:
                    pg = db["postgresql"]
                    self.database.host = pg.get("host", self.database.host)
                    self.database.port = pg.get("port", self.database.port)
                    self.database.database_name = pg.get("database", self.database.database_name)
                    self.database.username = pg.get("user", self.database.username)
                    self.database.password = pg.get("password", self.database.password)
                    self.database.pg_pool_size = pg.get("pool_size", self.database.pg_pool_size)
                    self.database.pg_max_overflow = pg.get("max_overflow", self.database.pg_max_overflow)
                    self.database.pg_slot_budget = pg.get("slot_budget", self.database.pg_slot_budget)

                # Fallback: support legacy top-level keys under database
                # e.g., host, port, name/database, user/username, pool_size
                self.database.host = db.get("host", self.database.host)
                self.database.port = db.get("port", self.database.port)
                # Prefer 'database_name' then 'name'
                self.database.database_name = db.get("database_name", db.get("name", self.database.database_name))
                # Prefer 'username' then 'user'
                self.database.username = db.get("username", db.get("user", self.database.username))
                # Do not read password from file by default; env overrides handled in _load_from_env
                self.database.pg_pool_size = db.get("pool_size", self.database.pg_pool_size)
                self.database.pg_max_overflow = db.get("max_overflow", self.database.pg_max_overflow)
                self.database.pg_slot_budget = db.get("slot_budget", self.database.pg_slot_budget)

            # Logging configuration
            if "logging" in data:
                log = data["logging"]
                self.logging.level = log.get("level", self.logging.level)
                self.logging.file = Path(log.get("file", self.logging.file))
                self.logging.max_size = log.get("max_size", self.logging.max_size)
                self.logging.max_files = log.get("max_files", self.logging.max_files)

            # Session configuration
            if "session" in data:
                sess = data["session"]
                self.session.timeout = sess.get("timeout", self.session.timeout)
                self.session.max_concurrent = sess.get("max_concurrent", self.session.max_concurrent)
                self.session.cleanup_interval = sess.get("cleanup_interval", self.session.cleanup_interval)

            # Agent configuration
            if "agents" in data:
                ag = data["agents"]
                self.agent.max_agents = ag.get("max_per_project", self.agent.max_agents)

            # Message configuration
            if "messages" in data:
                msg = data["messages"]
                self.message.max_queue_size = msg.get("max_queue_size", self.message.max_queue_size)
                self.message.batch_size = msg.get("batch_size", self.message.batch_size)
                self.message.max_retries = msg.get("retry_attempts", self.message.max_retries)
                self.message.retry_delay = msg.get("retry_delay", self.message.retry_delay)

            # Upload configuration (SEC-0001 Phase 2)
            if "upload" in data:
                up = data["upload"]
                self.upload.max_upload_bytes = int(up.get("max_bytes", self.upload.max_upload_bytes))
                self.upload.sniff_bytes = int(up.get("sniff_bytes", self.upload.sniff_bytes))
                exts = up.get("allowed_extensions")
                if exts is not None:
                    self.upload.allowed_extensions = tuple(exts)

            # Tenant configuration
            if "tenant" in data:
                tn = data["tenant"]
                self.tenant.enable_multi_tenant = tn.get("enabled", self.tenant.enable_multi_tenant)
                self.tenant.default_tenant_key = tn.get("default_key", self.tenant.default_tenant_key)
                self.tenant.key_header = tn.get("key_header", self.tenant.key_header)
                # Handle isolation_strict -> tenant_isolation_level conversion
                if "isolation_strict" in tn:
                    self.tenant.tenant_isolation_level = "strict" if tn["isolation_strict"] else "relaxed"

            # Setup mode flag (allows placeholder password during initial wizard setup)
            if "setup_mode" in data:
                self.setup_mode = data.get("setup_mode", False)

        except Exception as e:  # Broad catch: wraps in ConfigValidationError
            logger.exception("Error loading config file")
            raise ConfigValidationError(f"Failed to load config file: {e}") from e

    def _load_from_env(self):
        """Override configuration with environment variables."""
        # Server settings
        # GILJO_MCP_MODE environment variable removed in v3.0

        if port := os.getenv("GILJO_MCP_SERVER_PORT"):
            self.server.mcp_port = int(port)

        if port := os.getenv("GILJO_MCP_API_PORT"):
            self.server.api_port = int(port)

        if port := os.getenv("GILJO_API_PORT"):  # Alternative env var from tests
            self.server.api_port = int(port)

        if port := os.getenv("GILJO_MCP_WEBSOCKET_PORT"):
            self.server.websocket_port = int(port)

        if port := os.getenv("GILJO_MCP_DASHBOARD_PORT"):
            self.server.dashboard_port = int(port)

        if api_key := os.getenv("GILJO_MCP_API_KEY"):
            self.server.api_key = api_key

        if host := os.getenv("GILJO_API_HOST"):  # From tests
            self.server.api_host = host

        # Database settings
        if db_type := os.getenv("DB_TYPE"):
            self.database.type = db_type

        if db_url := os.getenv("GILJO_DATABASE_URL"):  # From tests
            self.database.database_url = db_url

        if db_host := os.getenv("DB_HOST"):
            self.database.host = db_host

        if db_port := os.getenv("DB_PORT"):
            self.database.port = int(db_port)

        if db_name := os.getenv("DB_NAME"):
            self.database.database_name = db_name

        if db_user := os.getenv("DB_USER"):
            self.database.username = db_user

        if db_password := os.getenv("DB_PASSWORD"):
            self.database.password = db_password

        # INF-3009a: explicit DB pool knobs (the authoritative, env-driven pool config).
        # Safe int parse — a bad value keeps the existing default rather than crashing boot.
        for env_name, attr in (
            ("GILJO_PG_POOL_SIZE", "pg_pool_size"),
            ("GILJO_PG_MAX_OVERFLOW", "pg_max_overflow"),
            ("GILJO_DB_SLOT_BUDGET", "pg_slot_budget"),
        ):
            if raw := os.getenv(env_name):
                try:
                    setattr(self.database, attr, int(raw))
                except ValueError:
                    logger.warning("Invalid %s=%r; keeping default %s", env_name, raw, getattr(self.database, attr))

        # Logging settings
        if log_level := os.getenv("LOG_LEVEL"):
            self.logging.level = log_level

        # Upload settings (SEC-0001 Phase 2)
        if max_upload := os.getenv("GILJO_MAX_UPLOAD_BYTES"):
            try:
                self.upload.max_upload_bytes = int(max_upload)
            except ValueError:
                logger.warning("Invalid GILJO_MAX_UPLOAD_BYTES=%r; keeping default", max_upload)

    def validate(self):
        """Validate configuration for correctness and consistency."""
        errors = []

        # Port validation
        ports = [
            self.server.mcp_port,
            self.server.api_port,
            self.server.websocket_port,
            self.server.dashboard_port,
        ]

        if len(ports) != len(set(ports)):
            errors.append("Port conflict: All service ports must be unique")

        errors.extend(
            [f"Invalid port {port}: Must be between 1024 and 65535" for port in ports if not 1024 <= port <= 65535]
        )

        # Database validation
        if self.database.type != "postgresql":
            errors.append(f"Only PostgreSQL is supported. Got: {self.database.type}")

        # Only require password if no database URL is provided (for PostgreSQL)
        # Check if we're in setup mode (allows placeholder password during initial setup)
        if (
            self.database.type == "postgresql"
            and not self.database.database_url
            and not self.database.password
            and not os.getenv("DB_PASSWORD")
            and not getattr(self, "setup_mode", False)
        ):
            errors.append("PostgreSQL password is required")

        # Agent configuration validation
        if self.agent.max_agents < 1:
            errors.append("Must allow at least 1 agent per project")

        # Message configuration validation
        if self.message.max_retries < 0:
            errors.append("Retry attempts must be non-negative")

        if self.message.batch_size > self.message.max_queue_size:
            errors.append("Batch size cannot exceed max queue size")

        # Mode-specific validation removed in v3.0
        # Authentication is always enabled, controlled by middleware

        if errors:
            error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            raise ConfigValidationError(error_msg)

    def reload(self):
        """Reload configuration from file and environment."""
        logger.info("Reloading configuration...")

        try:
            self.load()
            logger.info("Configuration reloaded successfully")
        except Exception as _exc:  # Broad catch: config reload boundary, logs and re-raises
            logger.exception("Failed to reload configuration")
            raise

    def _setup_file_watcher(self):
        """Setup file watcher for hot-reloading."""
        if self._observer:
            self._observer.stop()

        self._observer = Observer()
        # Daemon: the config hot-reload watcher must never block process /
        # interpreter exit. Without this its non-daemon threads linger after a
        # test session and hang teardown (the intermittent CI hang root cause).
        self._observer.daemon = True
        handler = ConfigFileWatcher(self)

        # Watch the config file's directory
        watch_dir = self.config_path.parent
        self._observer.schedule(handler, str(watch_dir), recursive=False)
        self._observer.start()

        logger.info(f"Config file watcher started for {self.config_path}")

    def stop_watching(self):
        """Stop the file watcher."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None

    def get_all_settings(self) -> dict[str, Any]:
        """Get all configuration settings as a dictionary."""
        return {
            "server": {
                "mcp": {
                    "host": self.server.mcp_host,
                    "port": self.server.mcp_port,
                    "transport": self.server.mcp_transport,
                },
                "api": {
                    "host": self.server.api_host,
                    "port": self.server.api_port,
                    "cors_enabled": self.server.api_cors_enabled,
                },
                "websocket": {
                    "enabled": self.server.websocket_enabled,
                    "port": self.server.websocket_port,
                },
                "dashboard": {
                    "enabled": self.server.dashboard_enabled,
                    "host": self.server.dashboard_host,
                    "port": self.server.dashboard_port,
                    "dev_server_port": self.server.dashboard_dev_port,
                },
            },
            "database": {
                "type": self.database.type,
                "postgresql": {
                    "host": self.database.host,
                    "port": self.database.port,
                    "database": self.database.database_name,
                    "user": self.database.username,
                    "password": "",  # Don't save passwords to file
                    "pool_size": self.database.pg_pool_size,
                    "max_overflow": self.database.pg_max_overflow,
                    "slot_budget": self.database.pg_slot_budget,
                },
            },
            "logging": {
                "level": self.logging.level,
                "file": str(self.logging.file),
                "max_size": self.logging.max_size,
                "max_files": self.logging.max_files,
            },
            "session": {
                "timeout": self.session.timeout,
                "max_concurrent": self.session.max_concurrent,
                "cleanup_interval": self.session.cleanup_interval,
            },
            "agents": {
                "max_per_project": self.agent.max_agents,
            },
            "messages": {
                "max_queue_size": self.message.max_queue_size,
                "batch_size": self.message.batch_size,
                "retry_attempts": self.message.max_retries,
                "retry_delay": self.message.retry_delay,
            },
            "upload": {
                "max_bytes": self.upload.max_upload_bytes,
                "allowed_extensions": list(self.upload.allowed_extensions),
                "sniff_bytes": self.upload.sniff_bytes,
            },
            "tenant": {
                "enabled": self.tenant.enable_multi_tenant,
                "default_key": self.tenant.default_tenant_key,
                "key_header": self.tenant.key_header,
                "isolation_strict": self.tenant.tenant_isolation_level == "strict",
            },
        }

    def create_database_manager(self, tenant_key: str | None = None):
        """
        Create a DatabaseManager instance with current configuration.

        Args:
            tenant_key: Optional tenant key for multi-tenant database separation

        Returns:
            DatabaseManager instance configured for this environment
        """
        from giljo_mcp.database import DatabaseManager

        # Get connection string with optional tenant separation
        connection_string = self.database.get_connection_string(tenant_key)

        # v3.0: Always use async for better performance.
        # INF-3009a: pass the explicit, authoritative pool knob (no psutil heuristic).
        return DatabaseManager(
            database_url=connection_string,
            is_async=True,
            pool_size=self.database.pg_pool_size,
            max_overflow=self.database.pg_max_overflow,
        )

    @classmethod
    def load_from_file(cls, path: Path) -> "ConfigManager":
        """Load configuration from a specific file."""
        return cls(config_path=path, auto_reload=False)

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - stop file watcher."""
        self.stop_watching()

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value by dot-separated key path.
        Supports both attribute access and dictionary traversal.

        Args:
            key: Dot-separated path (e.g., "server.api_port" or "services.external_host")
            default: Default value if key not found

        Returns:
            Configuration value or default

        Examples:
            config.get("server.api_port")  # Attribute access
            config.get("services.external_host")  # Dictionary traversal
        """
        parts = key.split(".")
        value = self

        try:
            for part in parts:
                if hasattr(value, part):
                    # Attribute access (existing behavior)
                    value = getattr(value, part)
                elif isinstance(value, dict):
                    # Dictionary traversal (new behavior)
                    value = value.get(part)
                    if value is None:
                        return default
                else:
                    return default
            return value
        except (AttributeError, TypeError, KeyError):
            return default

    def get_nested(self, dotted_key: str, default: Any = None) -> Any:
        """Access nested config.yaml values using dot notation.

        Walks the raw config dict (not the typed dataclass attributes).
        Use this when you need YAML key paths that aren't mapped into the
        typed ConfigManager attributes (e.g., ``features.serena_mcp.use_in_prompts``,
        ``health_monitoring.timeouts.waiting_timeout``).

        The implementation can be changed later (e.g., check env vars first,
        then file config) without changing any caller.

        Args:
            dotted_key: Dot-separated key path (e.g., "database.host")
            default: Value to return if key path doesn't exist

        Returns:
            The config value, or *default* if any segment is missing.
        """
        _missing = object()
        current: Any = self._raw_config
        for segment in dotted_key.split("."):
            if isinstance(current, dict):
                current = current.get(segment, _missing)
                if current is _missing:
                    return default
            else:
                return default
        return current


# Module-level configuration holder
class _ConfigManagerHolder:
    """Lazy singleton holder to avoid global statement."""

    _instance: ConfigManager | None = None

    @classmethod
    def get_instance(cls) -> ConfigManager:
        if cls._instance is None:
            cls._instance = ConfigManager(auto_reload=True)
            cls._instance.logging.setup_logging()
        return cls._instance

    @classmethod
    def set_instance(cls, config: ConfigManager):
        cls._instance = config


def get_config() -> ConfigManager:
    """Get the global configuration manager instance."""
    return _ConfigManagerHolder.get_instance()
