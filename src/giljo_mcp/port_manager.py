# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import os
import socket
from dataclasses import dataclass
from pathlib import Path

import yaml

from giljo_mcp._config_io import read_config


logger = logging.getLogger(__name__)


@dataclass
class PortConfiguration:

    api_port: int = 7272

    frontend_port: int = 7274

    postgres_port: int = 5432

    api_alternatives: list[int] = None
    frontend_alternatives: list[int] = None

    def __post_init__(self):
        if self.api_alternatives is None:
            self.api_alternatives = [7273, 7274, 8747, 8823, 9456, 9789]
        if self.frontend_alternatives is None:
            self.frontend_alternatives = [6001, 6002, 6003, 5173, 5174]


class PortManager:

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or Path("./config.yaml")
        self.config = PortConfiguration()

    @staticmethod
    def check_port_available(port: int, host: str = "127.0.0.1") -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                result = sock.connect_ex((host, port))
                return result != 0
        except (OSError, ValueError) as e:
            logger.debug(f"Error checking port {port}: {e}")
            return False

    @staticmethod
    def find_available_port(preferred: int, alternatives: list[int | None] = None) -> int:
        if PortManager.check_port_available(preferred):
            return preferred

        if alternatives:
            for port in alternatives:
                if PortManager.check_port_available(port):
                    logger.warning(f"Port {preferred} is occupied, using alternative port {port}")
                    return port

        import random

        for _ in range(10):
            port = random.randint(7200, 9999)
            if PortManager.check_port_available(port):
                logger.warning(f"Using random available port {port} (preferred {preferred} was occupied)")
                return port

        raise RuntimeError(f"Could not find available port (preferred: {preferred})")

    def load_from_config_file(self) -> bool:
        if not self.config_path.exists():
            logger.debug(f"Config file not found: {self.config_path}")
            return False

        try:
            data = read_config(self.config_path)

            if "services" in data:
                services = data["services"]

                if "api" in services and isinstance(services["api"], dict) and "port" in services["api"]:
                    self.config.api_port = services["api"]["port"]
                    logger.debug(f"Loaded API port from services config: {self.config.api_port}")

                if "frontend" in services and isinstance(services["frontend"], dict) and "port" in services["frontend"]:
                    self.config.frontend_port = services["frontend"]["port"]
                    logger.debug(f"Loaded frontend port from services config: {self.config.frontend_port}")

                if "database" in data and isinstance(data["database"], dict) and "port" in data["database"]:
                    self.config.postgres_port = data["database"]["port"]
                    logger.debug(f"Loaded PostgreSQL port from database config: {self.config.postgres_port}")

                logger.info(f"Loaded port configuration from {self.config_path}")
                return True

            if "server" in data:
                server = data["server"]

                if "port" in server and isinstance(server["port"], int):
                    self.config.api_port = server["port"]
                    logger.debug(f"Loaded unified server port from config: {self.config.api_port}")

                if "api" in server and isinstance(server["api"], dict) and "port" in server["api"]:
                    self.config.api_port = server["api"]["port"]
                    logger.debug(f"Loaded API port from config: {self.config.api_port}")

                if "frontend_port" in server:
                    self.config.frontend_port = server["frontend_port"]
                elif "dashboard" in server and isinstance(server["dashboard"], dict) and "port" in server["dashboard"]:
                    self.config.frontend_port = server["dashboard"]["port"]

                logger.info(f"Loaded port configuration from {self.config_path}")
                return True

            logger.debug("No 'services' or 'server' section found in config")
            return False

        except (OSError, ValueError, yaml.YAMLError):
            logger.exception("Error loading port configuration from {self.config_path}")
            return False

    def load_from_environment(self) -> bool:
        loaded = False

        api_port_vars = ["GILJO_PORT", "GILJO_API_PORT", "GILJO_MCP_API_PORT"]
        for var_name in api_port_vars:
            if port_str := os.getenv(var_name):
                try:
                    port = int(port_str)
                    if 1024 <= port <= 65535:
                        self.config.api_port = port
                        logger.info(f"Loaded API port from {var_name}: {port}")
                        loaded = True
                        break
                except ValueError:
                    logger.warning(f"Invalid port value in {var_name}: {port_str}")

        frontend_port_vars = ["GILJO_FRONTEND_PORT", "GILJO_MCP_DASHBOARD_PORT"]
        for var_name in frontend_port_vars:
            if port_str := os.getenv(var_name):
                try:
                    port = int(port_str)
                    if 1024 <= port <= 65535:
                        self.config.frontend_port = port
                        logger.info(f"Loaded frontend port from {var_name}: {port}")
                        loaded = True
                        break
                except ValueError:
                    logger.warning(f"Invalid port value in {var_name}: {port_str}")

        if port_str := os.getenv("POSTGRES_PORT") or os.getenv("DB_PORT"):
            try:
                port = int(port_str)
                if 1024 <= port <= 65535:
                    self.config.postgres_port = port
                    logger.info(f"Loaded PostgreSQL port from environment: {port}")
                    loaded = True
            except ValueError:
                logger.warning(f"Invalid PostgreSQL port value: {port_str}")

        return loaded

    def load_configuration(self) -> PortConfiguration:

        self.load_from_config_file()

        self.load_from_environment()

        logger.info(
            f"Port configuration loaded - API: {self.config.api_port}, "
            f"Frontend: {self.config.frontend_port}, "
            f"PostgreSQL: {self.config.postgres_port}"
        )

        return self.config

    def get_api_port(self, check_availability: bool = False) -> int:
        if not check_availability:
            return self.config.api_port

        return self.find_available_port(self.config.api_port, self.config.api_alternatives)

    def get_frontend_port(self, check_availability: bool = False) -> int:
        if not check_availability:
            return self.config.frontend_port

        return self.find_available_port(self.config.frontend_port, self.config.frontend_alternatives)


def get_port_manager(config_path: Path | None = None) -> PortManager:
    manager = PortManager(config_path)
    manager.load_configuration()
    return manager


def get_api_port(config_path: Path | None = None, check_availability: bool = False) -> int:
    manager = get_port_manager(config_path)
    return manager.get_api_port(check_availability)


def get_frontend_port(config_path: Path | None = None, check_availability: bool = False) -> int:
    manager = get_port_manager(config_path)
    return manager.get_frontend_port(check_availability)
