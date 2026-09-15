# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations


def test_free_functions_importable_from_mission_assembly() -> None:
    from giljo_mcp.services.mission_assembly import (
        assemble_mission_context,
        compute_protocol_etag,
    )

    assert callable(assemble_mission_context)
    assert callable(compute_protocol_etag)


def test_back_compat_shims_still_present_on_mission_service() -> None:
    from giljo_mcp.services.mission_service import MissionService

    assert hasattr(MissionService, "_assemble_mission_context")
    assert hasattr(MissionService, "_compute_protocol_etag")


def test_compute_etag_shim_delegates_to_free_function() -> None:
    from giljo_mcp.services.mission_assembly import compute_protocol_etag
    from giljo_mcp.services.mission_service import MissionService

    assert MissionService._compute_protocol_etag("ID", "PROTO") == compute_protocol_etag("ID", "PROTO")
    assert MissionService._compute_protocol_etag(None, None) == compute_protocol_etag(None, None)


def test_compute_etag_is_stable_and_collision_resistant() -> None:
    from giljo_mcp.services.mission_assembly import compute_protocol_etag

    assert compute_protocol_etag("ID", "PROTO") == compute_protocol_etag("ID", "PROTO")
    assert compute_protocol_etag("AB", "C") != compute_protocol_etag("A", "BC")
