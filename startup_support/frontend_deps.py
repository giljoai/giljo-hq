# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import json
from pathlib import Path


def _dev_dependency_names(frontend_dir: Path) -> list[str]:
    try:
        manifest = json.loads((frontend_dir / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return list((manifest.get("devDependencies") or {}).keys())


def frontend_deps_need_install(frontend_dir: Path, *, include_dev: bool) -> bool:
    node_modules = frontend_dir / "node_modules"
    marker = node_modules / ".package-lock.json"
    lockfile = frontend_dir / "package-lock.json"
    if not marker.exists():
        return True
    if lockfile.exists() and lockfile.stat().st_mtime > marker.stat().st_mtime:
        return True
    if include_dev:
        return any(not (node_modules / name / "package.json").exists() for name in _dev_dependency_names(frontend_dir))
    return False
