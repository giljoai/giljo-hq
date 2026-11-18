# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolConnectedRow(BaseModel):
    """Whether an AI tool has connected to this account."""

    done: bool = Field(description="True once a tool is connected now or was connected at some earlier time.")
    live: bool = Field(description="True only while a tool is connected right now, not just in the past.")
    tool_name: str | None = Field(description="The tool's display name when exactly one is known, otherwise null.")


class SkillsInstalledRow(BaseModel):
    """Whether a connected tool has run the setup request and received the skills."""

    done: bool


class ProductExistsRow(BaseModel):
    """Whether the account has a named product."""

    done: bool
    product_name: str | None = Field(description="The default product's name, else the newest named product's.")


class ProjectCreatedRow(BaseModel):
    """Whether the account has created a project."""

    done: bool = Field(description="True when the account has at least one project that is not deleted.")
    project_id: str | None = Field(description="The first project the account created that is not deleted, else null.")
    project_name: str | None = Field(description="That project's name, otherwise null.")


class ProjectStagedRow(BaseModel):
    """Whether a first project has been staged."""

    done: bool
    has_project: bool = Field(description="True when the account has at least one project that is not deleted.")
    mode: Literal["subagent", "multi_terminal"] | None = Field(
        description="How the newest staged project will run, or null when none is staged or no mode was chosen."
    )
    requested: bool = Field(
        default=False,
        description="True while the step is not done and the Stage prompt was handed out but no plan exists yet.",
    )


class ProjectBuiltRow(BaseModel):
    """Whether a first project has been built, closed and reviewed."""

    done: bool = Field(
        description="True once a built project was reviewed (or finished before reviews existed); it stays true if deleted."
    )
    in_progress: bool = Field(
        description="True while a launched project is still running (not cancelled, parked, deleted)."
    )
    awaiting_review: bool = Field(
        default=False,
        description="True when a project was built and closed but no built project has been reviewed yet.",
    )


class StartListRows(BaseModel):
    """The six first steps, each read from what the account has really done."""

    tool_connected: ToolConnectedRow
    skills_installed: SkillsInstalledRow
    product_exists: ProductExistsRow
    project_created: ProjectCreatedRow
    project_staged: ProjectStagedRow
    project_built: ProjectBuiltRow


class StartListResult(BaseModel):
    """Which of the six first steps this account has really done.

    Computed on the fly from existing records. Nothing here can be ticked by a click, and
    the account is always the signed-in person's, never a request parameter.
    """

    rows: StartListRows
    done_count: int = Field(ge=0, le=6, description="How many of the six steps are done.")
    step_count: int = Field(default=6, description="How many steps there are.")

    model_config = ConfigDict(from_attributes=True)
