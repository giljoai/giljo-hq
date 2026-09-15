# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations


CANONICAL_CLOSEOUT_STEPS: tuple[str, ...] = (
    "complete_job(job_id='{job_id}') -- complete yourself first",
    "write_project_closeout(force=false) -- writes the 360 closeout entry and finalizes "
    "the project (should now pass since all agents are complete)",
)


def build_required_sequence(job_id: str) -> list[str]:
    return [f"{i}. {step.format(job_id=job_id)}" for i, step in enumerate(CANONICAL_CLOSEOUT_STEPS, start=1)]
