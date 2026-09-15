# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class HealthCheckConfig:

    waiting_timeout_minutes: int = 2
    active_no_progress_minutes: int = 5
    heartbeat_timeout_minutes: int = 10

    abandon_after_minutes: int = 1440

    timeout_overrides: dict[str, int] = field(
        default_factory=lambda: {
            "orchestrator": 15,
            "analyzer": 5,
            "implementer": 10,
            "tester": 8,
            "reviewer": 6,
            "documenter": 5,
        }
    )

    scan_interval_seconds: int = 300
    auto_fail_on_timeout: bool = False
    notify_orchestrator: bool = True

    def get_timeout_for_agent(self, agent_display_name: str) -> int:
        return self.timeout_overrides.get(agent_display_name, self.heartbeat_timeout_minutes)


@dataclass
class AgentHealthStatus:

    execution_id: str
    job_id: str
    agent_id: str
    agent_display_name: str
    current_status: str
    health_state: str
    last_update: datetime
    minutes_since_update: float
    issue_description: str
    recommended_action: str
    project_id: str = ""
    project_name: str = ""
    product_id: str = ""
