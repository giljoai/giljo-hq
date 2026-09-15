# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class ValidationError:

    rule_id: str
    severity: str
    message: str
    remediation: str | None = None

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
            "remediation": self.remediation,
        }


class ValidationRule(ABC):

    rule_id: str
    name: str
    severity: str

    @abstractmethod
    def validate(self, content: str, agent_display_name: str) -> ValidationError | None:
        pass


class MCPToolsPresenceRule(ValidationRule):

    rule_id = "CRITICAL_001_MCP_TOOLS"
    name = "MCP Tools Presence Check"
    severity = "critical"

    REQUIRED_TOOLS: ClassVar[list[str]] = [
        "report_progress",
        "complete_job",
        "post_to_thread",
        "get_thread_history",
    ]

    def validate(self, content: str, agent_display_name: str) -> ValidationError | None:
        missing_tools = [tool for tool in self.REQUIRED_TOOLS if tool not in content]

        if missing_tools:
            return ValidationError(
                rule_id=self.rule_id,
                severity=self.severity,
                message=f"Missing required MCP tools: {', '.join(missing_tools)}",
                remediation="Restore missing tools from system_instructions or reset template to defaults",
            )

        return None


class PlaceholderVerificationRule(ValidationRule):

    rule_id = "CRITICAL_002_PLACEHOLDERS"
    name = "Placeholder Verification"
    severity = "critical"

    REQUIRED_PLACEHOLDERS: ClassVar[list[str]] = ["agent_id", "tenant_key", "job_id"]

    def validate(self, content: str, agent_display_name: str) -> ValidationError | None:
        missing_placeholders = []

        for placeholder in self.REQUIRED_PLACEHOLDERS:
            pattern = r"\{" + placeholder + r"\}"
            if not re.search(pattern, content):
                missing_placeholders.append(f"{{{placeholder}}}")

        if missing_placeholders:
            return ValidationError(
                rule_id=self.rule_id,
                severity=self.severity,
                message=f"Missing required placeholders: {', '.join(missing_placeholders)}",
                remediation="Add required placeholders to template for runtime substitution",
            )

        malformed_patterns = [
            r"[^{]{[\w_]+}[^}]",
            r"\{\{[\w_]+\}\}",
        ]

        for pattern in malformed_patterns:
            if re.search(pattern, content):
                pass

        return None


class InjectionDetectionRule(ValidationRule):

    rule_id = "CRITICAL_003_INJECTION"
    name = "Injection Detection"
    severity = "critical"

    SQL_INJECTION_PATTERNS: ClassVar[list[str]] = [
        r"';\s*DROP\s+TABLE",
        r"'\s*OR\s+'\d'\s*=\s*'\d",
        r"'\s*UNION\s+SELECT",
        r"--\s*$",
        r"admin'--",
    ]

    COMMAND_INJECTION_PATTERNS: ClassVar[list[str]] = [
        r"&&\s*rm\s+-rf",
        r"\|\s*cat\s+/etc/passwd",
        r";\s*whoami",
        r"`[^`]+`(?!``)",
        r"\$\([^)]+\)",
    ]

    SCRIPT_INJECTION_PATTERNS: ClassVar[list[str]] = [
        r"<script[^>]*>",
        r"onerror\s*=",
        r"javascript:",
        r"<iframe[^>]*>",
    ]

    def validate(self, content: str, agent_display_name: str) -> ValidationError | None:
        content_without_code_blocks = self._remove_code_blocks(content)

        detected_patterns = []

        detected_patterns.extend(
            [
                f"SQL injection pattern: {pattern}"
                for pattern in self.SQL_INJECTION_PATTERNS
                if re.search(pattern, content_without_code_blocks, re.IGNORECASE | re.MULTILINE)
            ]
        )

        detected_patterns.extend(
            [
                f"Command injection pattern: {pattern}"
                for pattern in self.COMMAND_INJECTION_PATTERNS
                if re.search(pattern, content_without_code_blocks)
            ]
        )

        detected_patterns.extend(
            [
                f"Script injection pattern: {pattern}"
                for pattern in self.SCRIPT_INJECTION_PATTERNS
                if re.search(pattern, content_without_code_blocks, re.IGNORECASE)
            ]
        )

        if detected_patterns:
            return ValidationError(
                rule_id=self.rule_id,
                severity=self.severity,
                message=f"Potential injection attack detected: {detected_patterns[0]}",
                remediation="Remove malicious content or reset template to system defaults",
            )

        return None

    def _remove_code_blocks(self, content: str) -> str:
        return re.sub(r"`[^`]+`", "", re.sub(r"```[\s\S]*?```", "", content))


class ToolUsageBestPracticesRule(ValidationRule):

    rule_id = "WARNING_001_BEST_PRACTICES"
    name = "Tool Usage Best Practices"
    severity = "warning"

    BEST_PRACTICE_KEYWORDS: ClassVar[list[str]] = [
        "error",
        "set_agent_status",
        "report_error",
        "handle errors",
        "gracefully",
    ]

    def validate(self, content: str, agent_display_name: str) -> ValidationError | None:
        error_handling_mentioned = any(keyword in content.lower() for keyword in self.BEST_PRACTICE_KEYWORDS)

        if not error_handling_mentioned:
            return ValidationError(
                rule_id=self.rule_id,
                severity=self.severity,
                message="Template does not mention error handling best practices",
                remediation="Consider adding guidance on using set_agent_status() and handling failures gracefully",
            )

        return None
