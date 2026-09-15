# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import hashlib
import json
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from giljo_mcp.validation.rules import (
    InjectionDetectionRule,
    MCPToolsPresenceRule,
    PlaceholderVerificationRule,
    ToolUsageBestPracticesRule,
    ValidationError,
    ValidationRule,
)


@dataclass
class TemplateValidationResult:

    is_valid: bool
    errors: list[ValidationError]
    warnings: list[ValidationError]
    template_id: str
    validated_at: datetime
    validation_duration_ms: float
    cached: bool = False

    @property
    def has_critical_errors(self) -> bool:
        return any(e.severity == "critical" for e in self.errors)

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "template_id": self.template_id,
            "validated_at": self.validated_at.isoformat(),
            "validation_duration_ms": self.validation_duration_ms,
            "cached": self.cached,
            "has_critical_errors": self.has_critical_errors,
        }


class TemplateValidator:

    CACHE_TTL_SECONDS = 3600

    def __init__(self, redis_client: Any | None = None):
        self.redis = redis_client
        self.rules: list[ValidationRule] = []
        self._lock = threading.Lock()
        self._register_core_rules()

    def validate(
        self, content: str, template_id: str, agent_display_name: str, use_cache: bool = True
    ) -> TemplateValidationResult:
        if use_cache and self.redis:
            cached = self._get_cached_result(template_id, content)
            if cached:
                return cached

        start_time = time.time()
        errors, warnings = self._run_all_rules(content, agent_display_name)
        duration_ms = (time.time() - start_time) * 1000

        is_valid = len([e for e in errors if e.severity == "critical"]) == 0

        result = TemplateValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            template_id=template_id,
            validated_at=datetime.now(UTC),
            validation_duration_ms=duration_ms,
            cached=False,
        )

        if use_cache and self.redis:
            self._cache_result(template_id, content, result)

        return result

    def _register_core_rules(self):
        self.rules = [
            MCPToolsPresenceRule(),
            PlaceholderVerificationRule(),
            InjectionDetectionRule(),
            ToolUsageBestPracticesRule(),
        ]

    def _run_all_rules(
        self, content: str, agent_display_name: str
    ) -> tuple[list[ValidationError], list[ValidationError]]:
        errors = []
        warnings = []

        for rule in self.rules:
            result = rule.validate(content, agent_display_name)

            if result is not None:
                if result.severity == "critical":
                    errors.append(result)
                else:
                    warnings.append(result)

        return errors, warnings

    def _get_cache_key(self, template_id: str, content: str) -> str:
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        return f"validation:{template_id}:{content_hash}"

    def _get_cached_result(self, template_id: str, content: str) -> TemplateValidationResult | None:
        if not self.redis:
            return None

        try:
            cache_key = self._get_cache_key(template_id, content)
            cached_data = self.redis.get(cache_key)

            if not cached_data:
                return None

            data = json.loads(cached_data)

            errors = [
                ValidationError(
                    rule_id=e["rule_id"], severity=e["severity"], message=e["message"], remediation=e.get("remediation")
                )
                for e in data["errors"]
            ]

            warnings = [
                ValidationError(
                    rule_id=w["rule_id"], severity=w["severity"], message=w["message"], remediation=w.get("remediation")
                )
                for w in data["warnings"]
            ]

            start_time = time.time()
            return TemplateValidationResult(
                is_valid=data["is_valid"],
                errors=errors,
                warnings=warnings,
                template_id=data["template_id"],
                validated_at=datetime.fromisoformat(data["validated_at"]),
                validation_duration_ms=(time.time() - start_time) * 1000,
                cached=True,
            )

        except (ValueError, KeyError, RuntimeError):
            # nosec B110
            return None

    def _cache_result(self, template_id: str, content: str, result: TemplateValidationResult):
        if not self.redis:
            return

        try:
            cache_key = self._get_cache_key(template_id, content)

            cache_data = {
                "is_valid": result.is_valid,
                "errors": [e.to_dict() for e in result.errors],
                "warnings": [w.to_dict() for w in result.warnings],
                "template_id": result.template_id,
                "validated_at": result.validated_at.isoformat(),
                "validation_duration_ms": result.validation_duration_ms,
            }

            self.redis.setex(cache_key, self.CACHE_TTL_SECONDS, json.dumps(cache_data))

        except (ValueError, KeyError, RuntimeError):
            pass  # nosec B110

    def clear_cache(self, template_id: str | None = None):
        if not self.redis:
            return

        try:
            if template_id:
                pattern = f"validation:{template_id}:*"
                keys = self.redis.keys(pattern)
                if keys:
                    self.redis.delete(*keys)
            else:
                pattern = "validation:*"
                keys = self.redis.keys(pattern)
                if keys:
                    self.redis.delete(*keys)

        except (ValueError, KeyError, RuntimeError):
            pass  # nosec B110
