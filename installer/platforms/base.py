# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List


class PlatformHandler(ABC):

    @property
    @abstractmethod
    def platform_name(self) -> str:
        pass

    @abstractmethod
    def get_venv_python(self, venv_dir: Path) -> Path:
        pass

    @abstractmethod
    def get_venv_pip(self, venv_dir: Path) -> Path:
        pass

    @abstractmethod
    def get_postgresql_scan_paths(self) -> List[Path]:
        pass

    @abstractmethod
    def get_postgresql_install_guide(self, recommended_version: int = 18) -> str:
        pass

    @abstractmethod
    def supports_desktop_shortcuts(self) -> bool:
        pass

    @abstractmethod
    def create_desktop_shortcuts(self, install_dir: Path, venv_dir: Path) -> Dict[str, Any]:
        pass

    @abstractmethod
    def run_npm_command(self, cmd: List[str], cwd: Path, timeout: int = 300) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_network_ips(self) -> List[str]:
        pass

    @abstractmethod
    def welcome_screen(self) -> None:
        pass

    @abstractmethod
    def get_platform_specific_warnings(self) -> List[str]:
        pass
