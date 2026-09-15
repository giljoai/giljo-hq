# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


class PostgreSQLDiscovery:

    MIN_VERSION = 16
    MAX_VERSION = 18
    RECOMMENDED_VERSION = 18

    def __init__(self, platform_handler: Optional[Any] = None):
        self.platform_handler = platform_handler
        self.logger = logging.getLogger(self.__class__.__name__)
        self.system = platform.system()

    def discover(self) -> Dict[str, Any]:
        result = {"found": False, "psql_path": None, "version": None, "version_string": None, "method": "NOT_FOUND"}

        self.logger.info("Searching for PostgreSQL in system PATH...")
        psql_path = shutil.which("psql")
        if psql_path:
            self.logger.info(f"Found psql in PATH: {psql_path}")
            result["found"] = True
            result["psql_path"] = Path(psql_path)
            result["method"] = "PATH"

            version_info = self.get_postgresql_version(psql_path)
            if version_info:
                result["version"] = version_info.get("version")
                result["version_string"] = version_info.get("version_string")

            return result

        self.logger.info("PostgreSQL not in PATH, scanning common locations...")
        common_locations = self._get_common_locations()

        for location in common_locations:
            psql_candidate = location / "psql" if self.system != "Windows" else location / "psql.exe"

            if psql_candidate.exists():
                self.logger.info(f"Found psql at: {psql_candidate}")
                result["found"] = True
                result["psql_path"] = psql_candidate
                result["method"] = "COMMON_LOCATION"

                version_info = self.get_postgresql_version(str(psql_candidate))
                if version_info:
                    result["version"] = version_info.get("version")
                    result["version_string"] = version_info.get("version_string")

                return result

        if self.platform_handler and hasattr(self.platform_handler, "find_postgresql"):
            self.logger.info("Using platform handler for PostgreSQL discovery...")
            handler_result = self.platform_handler.find_postgresql()
            if handler_result and handler_result.get("found"):
                return handler_result

        self.logger.warning("PostgreSQL not found in PATH or common locations")
        return result

    def _get_common_locations(self) -> List[Path]:
        locations = []

        if self.system == "Windows":
            program_files = Path("C:/Program Files")
            program_files_x86 = Path("C:/Program Files (x86)")

            for version in range(18, 13, -1):
                locations.extend(
                    [
                        program_files / f"PostgreSQL/{version}/bin",
                        program_files_x86 / f"PostgreSQL/{version}/bin",
                        program_files / f"PostgreSQL {version}/bin",
                    ]
                )

            locations.extend(
                [
                    program_files / "PostgreSQL/bin",
                    program_files / "edb/languagepack/v2/PostgreSQL/bin",
                ]
            )

            for drive in ["D:", "E:", "F:", "G:"]:
                locations.append(Path(f"{drive}/PostgreSQL/bin"))

        elif self.system == "Linux":
            locations.extend(
                [
                    Path("/usr/bin"),
                    Path("/usr/local/bin"),
                    Path("/usr/pgsql-18/bin"),
                    Path("/usr/pgsql-17/bin"),
                    Path("/usr/pgsql-16/bin"),
                    Path("/usr/pgsql-15/bin"),
                    Path("/usr/pgsql-14/bin"),
                    Path("/usr/lib/postgresql/18/bin"),
                    Path("/usr/lib/postgresql/17/bin"),
                    Path("/usr/lib/postgresql/16/bin"),
                    Path("/usr/lib/postgresql/15/bin"),
                    Path("/usr/lib/postgresql/14/bin"),
                    Path("/opt/postgresql/bin"),
                ]
            )

        elif self.system == "Darwin":
            locations.extend(
                [
                    Path("/usr/local/bin"),
                    Path("/opt/homebrew/bin"),
                    Path("/usr/local/opt/postgresql@18/bin"),
                    Path("/usr/local/opt/postgresql@17/bin"),
                    Path("/usr/local/opt/postgresql@16/bin"),
                    Path("/usr/local/opt/postgresql@15/bin"),
                    Path("/usr/local/opt/postgresql@14/bin"),
                    Path("/Library/PostgreSQL/18/bin"),
                    Path("/Library/PostgreSQL/17/bin"),
                    Path("/Library/PostgreSQL/16/bin"),
                    Path("/Library/PostgreSQL/15/bin"),
                    Path("/Library/PostgreSQL/14/bin"),
                    Path("/Applications/Postgres.app/Contents/Versions/latest/bin"),
                ]
            )

        return locations

    def get_postgresql_version(self, psql_path: str) -> Optional[Dict[str, Any]]:
        try:
            result = subprocess.run([psql_path, "--version"], capture_output=True, text=True, timeout=5)

            if result.returncode == 0:
                version_output = result.stdout.strip()
                self.logger.debug(f"Version output: {version_output}")

                match = re.search(r"(\d+)\.(\d+)", version_output)
                if match:
                    major_version = int(match.group(1))
                    return {"version": major_version, "version_string": version_output}

            return None

        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            self.logger.warning(f"Failed to get PostgreSQL version: {e}")
            return None

    def validate_custom_path(self, custom_path: str) -> Dict[str, Any]:
        result = {
            "valid": False,
            "psql_path": None,
            "version": None,
            "version_string": None,
            "method": "CUSTOM",
            "error": None,
        }

        try:
            custom_path_obj = Path(custom_path)

            if custom_path_obj.name.startswith("psql"):
                psql_path = custom_path_obj
            else:
                psql_path = custom_path_obj / ("psql.exe" if self.system == "Windows" else "psql")

            if not psql_path.exists():
                result["error"] = f"psql not found at {psql_path}"
                return result

            version_info = self.get_postgresql_version(str(psql_path))
            if not version_info:
                result["error"] = "Could not determine PostgreSQL version"
                return result

            result["valid"] = True
            result["psql_path"] = psql_path
            result["version"] = version_info.get("version")
            result["version_string"] = version_info.get("version_string")

            return result

        except Exception as e:
            result["error"] = f"Path validation failed: {str(e)}"
            return result

    def validate_version(self, version: int) -> Dict[str, Any]:
        if version < self.MIN_VERSION:
            return {
                "compatible": False,
                "message": f"PostgreSQL {version} is not supported. Minimum version: {self.MIN_VERSION}",
                "severity": "error",
            }
        elif version > self.MAX_VERSION:
            return {
                "compatible": True,
                "message": f"PostgreSQL {version} is newer than tested version {self.MAX_VERSION}. Compatibility not guaranteed.",
                "severity": "warning",
            }
        elif version < self.RECOMMENDED_VERSION:
            return {
                "compatible": True,
                "message": f"PostgreSQL {version} is supported but version {self.RECOMMENDED_VERSION} is recommended.",
                "severity": "warning",
            }
        else:
            return {
                "compatible": True,
                "message": f"PostgreSQL {version} - Excellent! This is the recommended version.",
                "severity": "ok",
            }


def find_postgresql() -> Dict[str, Any]:
    discovery = PostgreSQLDiscovery()
    return discovery.discover()


def _parse_lsclusters(output: str) -> List[tuple]:
    clusters: List[tuple] = []

    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        version_field, _cluster, port_field, status = fields[0], fields[1], fields[2], fields[3]
        if status.lower() != "online":
            continue
        try:
            major = int(version_field.split(".")[0])
            port = int(port_field)
        except ValueError:
            continue
        clusters.append((major, port))

    return clusters


def detect_cluster_port(current_port: int = 5432, timeout: int = 10) -> Optional[int]:
    logger = logging.getLogger(__name__)
    system = platform.system()

    if system == "Windows":
        return None

    if shutil.which("pg_lsclusters"):
        try:
            proc = subprocess.run(
                ["pg_lsclusters", "--no-header"],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            clusters = _parse_lsclusters(proc.stdout or "")
            if clusters:
                newest_major = max(major for major, _port in clusters)
                candidates = sorted(port for major, port in clusters if major == newest_major)
                port = current_port if current_port in candidates else candidates[0]
                logger.info("pg_lsclusters reports cluster %s on port %s", newest_major, port)
                return port
        except (subprocess.SubprocessError, OSError) as exc:
            logger.warning("pg_lsclusters probe failed: %s", exc)

    if shutil.which("psql"):
        cmd = ["psql", "-tAc", "SHOW port"]
        if system != "Darwin":
            cmd = ["sudo", "-n", "-u", "postgres", *cmd]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
            if proc.returncode == 0:
                try:
                    port = int((proc.stdout or "").strip())
                except ValueError:
                    logger.warning("Could not parse 'SHOW port' output")
                else:
                    logger.info("psql reports the server is listening on port %s", port)
                    return port
        except (subprocess.SubprocessError, OSError) as exc:
            logger.warning("psql port probe failed: %s", exc)

    return None
