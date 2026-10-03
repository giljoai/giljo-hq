# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect

from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_capability


def test_ch_capability_has_no_spawn_flag_to_default():
    assert "can_spawn_terminals" not in inspect.signature(_build_ch_capability).parameters
