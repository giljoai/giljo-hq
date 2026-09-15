# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.project_service._lifecycle_redirects import (
    ELIGIBLE_SUPERSEDE_SUCCESSOR_STATUSES,
    require_supersede_successor,
    validate_supersede_successor,
)


class _FakeProject:
    def __init__(self, project_id: str, status: ProjectStatus) -> None:
        self.id = project_id
        self.status = status


class TestEligibleSuccessorStatuses:
    def test_matches_fe9508_picker_list(self):
        assert {s.value for s in ELIGIBLE_SUPERSEDE_SUCCESSOR_STATUSES} == {"active", "completed", "inactive"}


class TestValidateSupersedeSuccessor:
    def test_noop_when_status_is_not_superseded(self):
        successor = _FakeProject("succ-1", ProjectStatus.CANCELLED)
        validate_supersede_successor("pred-1", {"status": ProjectStatus.ACTIVE}, successor)

    @pytest.mark.parametrize("eligible", [ProjectStatus.ACTIVE, ProjectStatus.COMPLETED, ProjectStatus.INACTIVE])
    def test_accepts_eligible_successor(self, eligible):
        successor = _FakeProject("succ-1", eligible)
        validate_supersede_successor(
            "pred-1", {"status": ProjectStatus.SUPERSEDED, "successor_project_id": "succ-1"}, successor
        )

    @pytest.mark.parametrize(
        "ineligible",
        [ProjectStatus.CANCELLED, ProjectStatus.TERMINATED, ProjectStatus.DELETED, ProjectStatus.SUPERSEDED],
    )
    def test_rejects_ineligible_successor(self, ineligible):
        successor = _FakeProject("succ-1", ineligible)
        with pytest.raises(ValidationError) as exc_info:
            validate_supersede_successor(
                "pred-1", {"status": ProjectStatus.SUPERSEDED, "successor_project_id": "succ-1"}, successor
            )
        assert exc_info.value.error_code == "SUPERSEDE_REQUIRES_SUCCESSOR"
        assert exc_info.value.context["successor_status"] == ineligible.value


class TestRequireSupersedeSuccessor:
    def test_noop_when_status_is_not_superseded(self):
        require_supersede_successor("pred-1", {"status": ProjectStatus.ACTIVE})

    def test_noop_when_successor_present(self):
        require_supersede_successor(
            "pred-1", {"status": ProjectStatus.SUPERSEDED, "successor_project_id": "succ-1"}
        )

    def test_raises_when_successor_absent(self):
        with pytest.raises(ValidationError) as exc_info:
            require_supersede_successor("pred-1", {"status": ProjectStatus.SUPERSEDED})
        assert exc_info.value.error_code == "SUPERSEDE_REQUIRES_SUCCESSOR"

    def test_raises_when_successor_explicitly_none(self):
        with pytest.raises(ValidationError) as exc_info:
            require_supersede_successor("pred-1", {"status": ProjectStatus.SUPERSEDED, "successor_project_id": None})
        assert exc_info.value.error_code == "SUPERSEDE_REQUIRES_SUCCESSOR"
