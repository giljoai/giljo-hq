# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from api.schemas.task import TaskCreate, TaskResponse, TaskUpdate


@pytest.mark.parametrize("model", [TaskCreate, TaskUpdate, TaskResponse])
def test_task_type_help_names_the_values_that_exist(model) -> None:
    description = model.model_fields["task_type"].description or ""

    assert "TSK" in description, description
    assert "HND" in description, description


@pytest.mark.parametrize("model", [TaskCreate, TaskUpdate, TaskResponse])
def test_task_type_help_no_longer_advertises_the_project_taxonomy(model) -> None:
    description = model.model_fields["task_type"].description or ""

    assert "BE, FE, INF" not in description, description
