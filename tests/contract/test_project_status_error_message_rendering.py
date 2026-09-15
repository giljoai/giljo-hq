# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.domain.project_status import ProjectStatus


_PRODUCTION_TEMPLATES: list[tuple[str, str]] = [
    (
        "ProjectService.update_project / update_project_mission immutable guard",
        "Cannot modify project in '{status.value}' status. Only inactive and active projects can be updated.",
    ),
    (
        "JobLifecycleService.spawn_agent_job immutable guard",
        "Cannot modify project in '{status.value}' status. Only inactive and active projects can be updated.",
    ),
    (
        "ProjectLifecycleService.activate_project guard",
        "Cannot activate project from status '{status.value}'",
    ),
    (
        "ProjectLifecycleService.deactivate_project guard",
        "Cannot deactivate project with status '{status.value}'",
    ),
    (
        "ProjectLifecycleService.continue_working guard",
        "Cannot resume project from status '{status.value}'. Project must be completed.",
    ),
    (
        "ProjectStagingService.cancel_staging precondition",
        "Cannot cancel staging: project status='{status.value}', staging_status='staging' (need INACTIVE + staging)",
    ),
]


@pytest.mark.parametrize(
    "label,template",
    _PRODUCTION_TEMPLATES,
    ids=[t[0] for t in _PRODUCTION_TEMPLATES],
)
@pytest.mark.parametrize(
    "member",
    [ProjectStatus.COMPLETED, ProjectStatus.CANCELLED, ProjectStatus.TERMINATED],
    ids=lambda m: m.value,
)
def test_status_error_messages_render_canonical_value(label: str, template: str, member: ProjectStatus) -> None:

    rendered = template.format(status=member)

    assert member.value in rendered, (
        f"Error message for '{label}' does not contain the canonical lowercase "
        f"status value '{member.value}'. Rendered: {rendered!r}. "
        f"This means the user sees the Python class name 'ProjectStatus.{member.name}' "
        f"instead of '{member.value}'. Fix the f-string to use {{status.value}}."
    )

    leaked_repr = f"ProjectStatus.{member.name}"
    assert leaked_repr not in rendered, (
        f"Error message for '{label}' leaks the Python enum repr '{leaked_repr}'. "
        f"Rendered: {rendered!r}. Format with {{status.value}} instead."
    )


def test_enum_member_format_behavior_is_documented() -> None:

    member = ProjectStatus.COMPLETED

    assert f"{member}" == "completed", (
        "ProjectStatus f-string format behavior changed. "
        "ProjectStatus is an enum.StrEnum whose __format__ returns the value, "
        'so f"{member}" must render "completed", not the "ProjectStatus.COMPLETED" repr. '
        "If this fails, the enum was likely changed away from StrEnum -- that "
        "reintroduces the BE-5039 enum-format leak in user-facing error messages."
    )

    assert f"{member.value}" == "completed"
