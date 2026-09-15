# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import os


ENV_VAR = "GILJO_RUN_BACKGROUND_JOBS"

_FALSEY = {"0", "false", "no", "off"}


def should_run_background_jobs() -> bool:
    raw = os.environ.get(ENV_VAR, "").strip().lower()
    if raw == "":
        return True
    return raw not in _FALSEY
