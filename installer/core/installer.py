# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pathlib
from typing import Any, Dict


class BaseInstaller:

    def __init__(self, settings: Dict[str, Any]):
        self.settings = settings
        self.install_dir = pathlib.Path(settings["install_dir"]) if "install_dir" in settings else None

        self.db_installer = None
        self.config_manager = None
        self.post_validator = None

    def create_venv(self) -> Dict[str, Any]:
        return {"success": True}

    def install_dependencies(self) -> Dict[str, Any]:
        return {"success": True}

    def install_frontend_dependencies(self) -> Dict[str, Any]:
        return {"success": True}

    def create_launchers(self) -> Dict[str, Any]:
        return {"success": True}

    def mode_specific_setup(self) -> Dict[str, Any]:
        return {"success": True}

    def install(self) -> Dict[str, Any]:
        steps = [
            ("create_venv", self.create_venv),
            ("db_setup", lambda: self.db_installer.setup() if self.db_installer else {"success": True}),
            (
                "config_generate",
                lambda: self.config_manager.generate_all() if self.config_manager else {"success": True},
            ),
            ("install_deps", self.install_dependencies),
            ("install_frontend", self.install_frontend_dependencies),
            ("create_launchers", self.create_launchers),
            ("mode_specific", self.mode_specific_setup),
            ("post_validate", lambda: self.post_validator.validate() if self.post_validator else {"valid": True}),
        ]

        for name, fn in steps:
            result = fn()
            if name == "post_validate":
                if not result.get("valid"):
                    return {"success": False, "error": f"Post-validation failed: {result}"}
                continue

            if not result.get("success"):
                return {"success": False, "error": f"{name} failed: {result}"}

        return {"success": True}


class LocalhostInstaller(BaseInstaller):

    def __init__(self, settings: Dict[str, Any]):
        super().__init__(settings)


class ServerInstaller(BaseInstaller):

    def __init__(self, settings: Dict[str, Any]):
        super().__init__(settings)
