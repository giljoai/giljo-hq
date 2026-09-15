# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .branding import PRODUCT_NAME
from .exceptions import ConfigValidationError


logger = logging.getLogger(__name__)




@dataclass
class ServerConfig:

    mcp_host: str = "0.0.0.0"
    mcp_port: int = 6001
    mcp_transport: str = "http"

    api_host: str = "0.0.0.0"
    api_port: int = 7272
    api_cors_enabled: bool = True
    api_key: str | None = None

    websocket_enabled: bool = True
    websocket_port: int = 6003

    dashboard_enabled: bool = True
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 7274
    dashboard_dev_port: int = 5173


@dataclass
class DatabaseConfig:

    type: str = "postgresql"
    database_name: str = "giljo_mcp.db"
    database_url: str | None = None

    host: str = "localhost"
    port: int = 5432
    username: str = "postgres"
    password: str = ""
    pg_pool_size: int = 5
    pg_max_overflow: int = 5
    pg_slot_budget: int = 90

    def get_connection_string(self, tenant_key: str | None = None) -> str:
        if self.database_url:
            return self.database_url

        if self.type == "postgresql":
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
                password = self.password or os.getenv("DB_PASSWORD", "")
                base_url = f"postgresql://{self.username}:{password}@{self.host}:{self.port}"

                if tenant_key:
                    return f"{base_url}/{self.database_name}_{tenant_key}"
                return f"{base_url}/{self.database_name}"
        else:
            raise ValueError(f"Unsupported database type: {self.type}")


@dataclass
class LoggingConfig:

    level: str = "INFO"
    file: Path = field(default_factory=lambda: Path("./logs/giljo_mcp.log"))
    max_size: str = "10MB"
    max_files: int = 5

    def setup_logging(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)

        log_level = getattr(logging, self.level.upper(), logging.INFO)

        from giljo_mcp.logging import _SafeRotatingFileHandler

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

    timeout: int = 3600
    max_concurrent: int = 10
    cleanup_interval: int = 300


@dataclass
class AgentConfig:

    max_agents: int = 20


@dataclass
class MessageConfig:

    max_queue_size: int = 1000
    message_timeout: int = 300
    max_retries: int = 3
    batch_size: int = 10
    retry_delay: float = 1.0


@dataclass
class UploadConfig:

    max_upload_bytes: int = 5_242_880
    allowed_extensions: tuple[str, ...] = (".txt", ".md", ".markdown")
    sniff_bytes: int = 8192


@dataclass
class TenantConfig:

    enable_multi_tenant: bool = True
    default_tenant_key: str | None = None
    tenant_isolation_level: str = "strict"
    key_header: str = "X-Tenant-Key"


class ConfigFileWatcher(FileSystemEventHandler):

    def __init__(self, config_manager: "ConfigManager"):
        self.config_manager = config_manager

    def on_modified(self, event: FileModifiedEvent):
        if not event.is_directory and event.src_path.endswith(".yaml"):
            logger.info(f"Config file changed: {event.src_path}")
            self.config_manager.reload()


class ConfigManager:

    def __init__(self, config_path: Path | None = None, auto_reload: bool = False):
        self.config_path = config_path or Path("./config.yaml")
        self.auto_reload = auto_reload
        self._lock = threading.RLock()
        self._observer = None

        self.server = ServerConfig()
        self.database = DatabaseConfig()
        self.logging = LoggingConfig()
        self.session = SessionConfig()
        self.agent = AgentConfig()
        self.message = MessageConfig()
        self.upload = UploadConfig()
        self.tenant = TenantConfig()

        self.app_name = PRODUCT_NAME
        self.app_version = "1.0.0"

        self._raw_config: dict = {}

        self.setup_mode = False

        self.load()

        if auto_reload:
            self._setup_file_watcher()


    def load(self):
        with self._lock:
            if self.config_path.exists():
                self._load_from_file()

            self._load_from_env()

            self.validate()

            logger.info("Configuration loaded successfully (v3.0 - mode detection removed)")

    def _migrate_v2_config(self, data: dict) -> dict:
        if "version" in data and data.get("version", "").startswith("3."):
            return data

        logger.info("Migrating v2.x config to v3.0 format")

        old_mode = data.get("server", {}).get("mode", "local")
        if "installation" in data and "mode" in data["installation"]:
            old_mode = data["installation"]["mode"]

        if "server" in data and "mode" in data["server"]:
            del data["server"]["mode"]

        if "installation" in data and "mode" in data["installation"]:
            del data["installation"]["mode"]

        data["version"] = "1.0.0"

        data["deployment_context"] = old_mode

        if "features" not in data:
            data["features"] = {}

        data["features"]["authentication"] = True
        data["features"]["auto_login_localhost"] = True
        data["features"]["firewall_configured"] = False

        if "server" not in data:
            data["server"] = {}

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
        try:
            with open(self.config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            data = self._migrate_v2_config(data)

            self._raw_config = data

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

            if "server" in data:
                srv = data["server"]
                self.server.api_key = srv.get("api_key", self.server.api_key)

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

            if "database" in data:
                db = data["database"]
                self.database.type = db.get("type", self.database.type)

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

                self.database.host = db.get("host", self.database.host)
                self.database.port = db.get("port", self.database.port)
                self.database.database_name = db.get("database_name", db.get("name", self.database.database_name))
                self.database.username = db.get("username", db.get("user", self.database.username))
                self.database.pg_pool_size = db.get("pool_size", self.database.pg_pool_size)
                self.database.pg_max_overflow = db.get("max_overflow", self.database.pg_max_overflow)
                self.database.pg_slot_budget = db.get("slot_budget", self.database.pg_slot_budget)

            if "logging" in data:
                log = data["logging"]
                self.logging.level = log.get("level", self.logging.level)
                self.logging.file = Path(log.get("file", self.logging.file))
                self.logging.max_size = log.get("max_size", self.logging.max_size)
                self.logging.max_files = log.get("max_files", self.logging.max_files)

            if "session" in data:
                sess = data["session"]
                self.session.timeout = sess.get("timeout", self.session.timeout)
                self.session.max_concurrent = sess.get("max_concurrent", self.session.max_concurrent)
                self.session.cleanup_interval = sess.get("cleanup_interval", self.session.cleanup_interval)

            if "agents" in data:
                ag = data["agents"]
                self.agent.max_agents = ag.get("max_per_project", self.agent.max_agents)

            if "messages" in data:
                msg = data["messages"]
                self.message.max_queue_size = msg.get("max_queue_size", self.message.max_queue_size)
                self.message.batch_size = msg.get("batch_size", self.message.batch_size)
                self.message.max_retries = msg.get("retry_attempts", self.message.max_retries)
                self.message.retry_delay = msg.get("retry_delay", self.message.retry_delay)

            if "upload" in data:
                up = data["upload"]
                self.upload.max_upload_bytes = int(up.get("max_bytes", self.upload.max_upload_bytes))
                self.upload.sniff_bytes = int(up.get("sniff_bytes", self.upload.sniff_bytes))
                exts = up.get("allowed_extensions")
                if exts is not None:
                    self.upload.allowed_extensions = tuple(exts)

            if "tenant" in data:
                tn = data["tenant"]
                self.tenant.enable_multi_tenant = tn.get("enabled", self.tenant.enable_multi_tenant)
                self.tenant.default_tenant_key = tn.get("default_key", self.tenant.default_tenant_key)
                self.tenant.key_header = tn.get("key_header", self.tenant.key_header)
                if "isolation_strict" in tn:
                    self.tenant.tenant_isolation_level = "strict" if tn["isolation_strict"] else "relaxed"

            if "setup_mode" in data:
                self.setup_mode = data.get("setup_mode", False)

        except Exception as e:
            logger.exception("Error loading config file")
            raise ConfigValidationError(f"Failed to load config file: {e}") from e

    def _load_from_env(self):

        if port := os.getenv("GILJO_MCP_SERVER_PORT"):
            self.server.mcp_port = int(port)

        if port := os.getenv("GILJO_MCP_API_PORT"):
            self.server.api_port = int(port)

        if port := os.getenv("GILJO_API_PORT"):
            self.server.api_port = int(port)

        if port := os.getenv("GILJO_MCP_WEBSOCKET_PORT"):
            self.server.websocket_port = int(port)

        if port := os.getenv("GILJO_MCP_DASHBOARD_PORT"):
            self.server.dashboard_port = int(port)

        if api_key := os.getenv("GILJO_MCP_API_KEY"):
            self.server.api_key = api_key

        if host := os.getenv("GILJO_API_HOST"):
            self.server.api_host = host

        if db_type := os.getenv("DB_TYPE"):
            self.database.type = db_type

        if db_url := os.getenv("GILJO_DATABASE_URL"):
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

        if log_level := os.getenv("LOG_LEVEL"):
            self.logging.level = log_level

        if max_upload := os.getenv("GILJO_MAX_UPLOAD_BYTES"):
            try:
                self.upload.max_upload_bytes = int(max_upload)
            except ValueError:
                logger.warning("Invalid GILJO_MAX_UPLOAD_BYTES=%r; keeping default", max_upload)

    def validate(self):
        errors = []

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

        if self.database.type != "postgresql":
            errors.append(f"Only PostgreSQL is supported. Got: {self.database.type}")

        if (
            self.database.type == "postgresql"
            and not self.database.database_url
            and not self.database.password
            and not os.getenv("DB_PASSWORD")
            and not getattr(self, "setup_mode", False)
        ):
            errors.append("PostgreSQL password is required")

        if self.agent.max_agents < 1:
            errors.append("Must allow at least 1 agent per project")

        if self.message.max_retries < 0:
            errors.append("Retry attempts must be non-negative")

        if self.message.batch_size > self.message.max_queue_size:
            errors.append("Batch size cannot exceed max queue size")


        if errors:
            error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            raise ConfigValidationError(error_msg)

    def reload(self):
        logger.info("Reloading configuration...")

        try:
            self.load()
            logger.info("Configuration reloaded successfully")
        except Exception as _exc:
            logger.exception("Failed to reload configuration")
            raise

    def _setup_file_watcher(self):
        if self._observer:
            self._observer.stop()

        self._observer = Observer()
        self._observer.daemon = True
        handler = ConfigFileWatcher(self)

        watch_dir = self.config_path.parent
        self._observer.schedule(handler, str(watch_dir), recursive=False)
        self._observer.start()

        logger.info(f"Config file watcher started for {self.config_path}")

    def stop_watching(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None

    def get_all_settings(self) -> dict[str, Any]:
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
                    "password": "",
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
        from giljo_mcp.database import DatabaseManager

        connection_string = self.database.get_connection_string(tenant_key)

        return DatabaseManager(
            database_url=connection_string,
            is_async=True,
            pool_size=self.database.pg_pool_size,
            max_overflow=self.database.pg_max_overflow,
        )

    @classmethod
    def load_from_file(cls, path: Path) -> "ConfigManager":
        return cls(config_path=path, auto_reload=False)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_watching()

    def get(self, key: str, default: Any = None) -> Any:
        parts = key.split(".")
        value = self

        try:
            for part in parts:
                if hasattr(value, part):
                    value = getattr(value, part)
                elif isinstance(value, dict):
                    value = value.get(part)
                    if value is None:
                        return default
                else:
                    return default
            return value
        except (AttributeError, TypeError, KeyError):
            return default

    def get_nested(self, dotted_key: str, default: Any = None) -> Any:
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


class _ConfigManagerHolder:

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
    return _ConfigManagerHolder.get_instance()
