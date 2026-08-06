# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Centralized Exception Hierarchy for Giljo HQ

This module provides a standardized exception hierarchy for consistent error handling
across the entire Giljo HQ system.
"""

from datetime import UTC


class BaseGiljoError(Exception):
    """
    Base exception for all Giljo HQ errors.

    All custom exceptions in the system should inherit from this base class
    to enable consistent error handling and categorization.
    """

    default_status_code: int = 500

    def __init__(self, message: str, error_code: str | None = None, context: dict | None = None):
        """
        Initialize the base exception.

        Args:
            message: Human-readable error message
            error_code: Optional machine-readable error code
            context: Optional dictionary with additional error context
        """
        from datetime import datetime

        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__.upper()
        self.context = context or {}
        self.timestamp = datetime.now(UTC)

    def __str__(self):
        if self.context:
            return f"{self.message} (Context: {self.context})"
        return self.message

    def to_dict(self) -> dict:
        """
        Convert exception to dictionary format for API responses.

        Returns:
            Dictionary containing error details
        """
        return {
            "error_code": self.error_code,
            "message": self.message,
            "context": self.context,
            "timestamp": self.timestamp.isoformat(),
            "status_code": self.default_status_code,
        }


# Configuration related exceptions
class ConfigValidationError(BaseGiljoError):
    """Raised when configuration validation fails."""


# Template related exceptions
class TemplateNotFoundError(BaseGiljoError):
    """Raised when a requested template cannot be found."""

    default_status_code: int = 404


# Orchestration related exceptions
class OrchestrationError(BaseGiljoError):
    """Base class for orchestration-related errors."""

    default_status_code: int = 500


class ProjectStateError(OrchestrationError):
    """Raised when project state is invalid for requested operation.

    A state conflict is a CLIENT error — the resource is in a state that does
    not permit the operation — so it maps to HTTP 409, not the 500 default that
    OrchestrationError carries for genuine server-side orchestration failures.
    HTTP surfaces that rely on the global handler (e.g. the project PATCH route)
    therefore return 409, and the handler logs it at WARNING rather than ERROR.
    The lifecycle endpoints already map it to 409 explicitly; this aligns the
    un-mapped paths with that intent.
    """

    default_status_code: int = 409


class ImplementationNotReadyError(OrchestrationError):
    """Raised when implementation is requested before the human gate has cleared.

    INF-6049b: the single shared implementation-readiness gate. The REST
    ``GET /api/prompts/implementation`` endpoint and the ``implement_project``
    MCP tool both reach this via ``ProjectStagingService.check_implementation_allowed``
    — neither copies the precondition checks.

    The human gate is SACRED (feedback_staging_stop_do_not_execute): nothing
    that raises this ever sets ``implementation_launched_at`` and there is no
    bypass. ``reason`` discriminates the two gate stages so each transport can
    surface the correct next action:

    - ``"staging_incomplete"``: ``staging_status`` is not ``'staging_complete'``.
    - ``"not_launched"``: ``implementation_launched_at`` is None (the user has
      not pressed Implement in the dashboard yet).

    Maps to HTTP 404 (mirrors the original inline checks that returned 404).
    """

    default_status_code: int = 404

    def __init__(self, reason: str, message: str, context: dict | None = None):
        super().__init__(message=message, context=context)
        self.reason = reason


# Database related exceptions
class DatabaseError(BaseGiljoError):
    """Base class for database-related errors."""

    default_status_code: int = 500


# Validation related exceptions
class ValidationError(BaseGiljoError):
    """Base class for validation errors."""

    default_status_code: int = 400


# API related exceptions
class AuthenticationError(BaseGiljoError):
    """Raised when API authentication fails."""

    default_status_code: int = 401


class AuthorizationError(BaseGiljoError):
    """Raised when API authorization fails."""

    default_status_code: int = 403


# Resource related exceptions
class ResourceNotFoundError(BaseGiljoError):
    """Raised when a requested resource cannot be found."""

    default_status_code: int = 404


class AlreadyExistsError(BaseGiljoError):
    """Raised when attempting to create a resource that already exists."""

    default_status_code: int = 409


class RetryExhaustedError(BaseGiljoError):
    """Raised when retry attempts are exhausted."""


# Context related exceptions
class ContextError(BaseGiljoError):
    """Base class for context-related errors."""


# File and path exceptions
class GiljoFileNotFoundError(BaseGiljoError):
    """Raised when a required file is not found."""
