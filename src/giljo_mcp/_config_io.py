# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from pathlib import Path
from typing import Any

import yaml


logger = logging.getLogger(__name__)


def get_config_path() -> Path:
    return Path.cwd() / "config.yaml"


def read_config(config_path: Path | None = None) -> dict[str, Any]:
    path = config_path or get_config_path()
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError):
        logger.exception("Failed to read %s", path)
        return {}


def write_config(config: dict[str, Any], config_path: Path | None = None) -> None:
    path = config_path or get_config_path()
    temp_path = path.with_suffix(".yaml.tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
    temp_path.replace(path)
