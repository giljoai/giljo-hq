# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Health monitoring configuration and data structures.

Provides configurable thresholds for agent health monitoring and
data structures for tracking health status.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class HealthCheckConfig:
    """
    Configurable thresholds for health monitoring.

    Attributes:
        waiting_timeout_minutes: Timeout for jobs stuck in 'waiting' state
        active_no_progress_minutes: Timeout for active jobs without progress updates
        heartbeat_timeout_minutes: Default timeout for complete silence
        timeout_overrides: Agent-type-specific timeout overrides
        scan_interval_seconds: How often to scan for unhealthy jobs
        auto_fail_on_timeout: Whether to automatically fail timed-out jobs
        notify_orchestrator: Whether to notify orchestrator of health issues
        abandon_after_minutes: Hard give-up ceiling past which a still-silent
            execution is decommissioned (terminal) so it stops re-alerting
    """

    # Timeout thresholds (minutes)
    waiting_timeout_minutes: int = 2
    active_no_progress_minutes: int = 5
    heartbeat_timeout_minutes: int = 10

    # BE-9101: hard give-up ceiling. Past this much continuous silence the
    # monitor transitions the execution to a terminal status ('decommissioned')
    # so it drops out of the active scan set and stops re-alerting forever.
    # Default 1440m = 24h = heartbeat_timeout_minutes (10) x 144 -- deliberately
    # generous so a merely-paused orchestrator (e.g. a human resuming an
    # overnight run) is never wrongly decommissioned; a full day of total
    # silence is unambiguously abandoned. Flat int, mirroring the sibling
    # threshold fields above (health_config carries no env-derived siblings).
    abandon_after_minutes: int = 1440

    # Per-agent type overrides
    timeout_overrides: dict[str, int] = field(
        default_factory=lambda: {
            "orchestrator": 15,  # Orchestrators get more time
            "analyzer": 5,
            "implementer": 10,
            "tester": 8,
            "reviewer": 6,
            "documenter": 5,
        }
    )

    # Monitoring behavior
    scan_interval_seconds: int = 300  # 5 minutes
    auto_fail_on_timeout: bool = False  # Conservative default
    notify_orchestrator: bool = True

    def get_timeout_for_agent(self, agent_display_name: str) -> int:
        """
        Get timeout for specific agent type.

        Args:
            agent_display_name: Type of agent (orchestrator, implementer, etc.)

        Returns:
            Timeout in minutes for this agent type
        """
        return self.timeout_overrides.get(agent_display_name, self.heartbeat_timeout_minutes)


@dataclass
class AgentHealthStatus:
    """
    Health status for a single agent execution.

    Attributes:
        execution_id: Primary key of AgentExecution (guaranteed unique)
        job_id: Job identifier (work order - may have multiple executions via succession)
        agent_id: Agent identifier (may have duplicates in edge cases)
        agent_display_name: Type of agent (orchestrator, implementer, etc.)
        current_status: Current execution status (waiting, working, blocked, complete, silent, decommissioned)
        health_state: Health state (healthy, warning, critical, timeout)
        last_update: Timestamp of last activity
        minutes_since_update: Minutes since last activity
        issue_description: Human-readable description of the issue
        recommended_action: Recommended remediation action
        project_id: Project ID for contextual alerts (empty if orphaned job)
        project_name: Project name for contextual alerts (empty if orphaned job)
        product_id: Product ID for contextual alerts (empty if orphaned job)
    """

    execution_id: str  # Primary key - guaranteed unique (AgentExecution.id)
    job_id: str
    agent_id: str  # Agent identifier (for WebSocket events)
    agent_display_name: str
    current_status: str  # Job status (waiting, active, etc.)
    health_state: str  # Health state (healthy, warning, critical, timeout)
    last_update: datetime
    minutes_since_update: float
    issue_description: str
    recommended_action: str
    project_id: str = ""
    project_name: str = ""
    product_id: str = ""
