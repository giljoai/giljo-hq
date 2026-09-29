# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import re
from datetime import UTC

from giljo_mcp.tenant import TENANT_KEY_SHAPE


_TENANT_KEY_RE = re.compile(TENANT_KEY_SHAPE)
_TENANT_KEY_REDACTION = "tk_[redacted]"


def _scrub(value):
    if isinstance(value, str):
        return _TENANT_KEY_RE.sub(_TENANT_KEY_REDACTION, value)
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


class BaseGiljoError(Exception):

    default_status_code: int = 500

    def __init__(self, message: str, error_code: str | None = None, context: dict | None = None):
        from datetime import datetime

        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__.upper()
        self.context = context or {}
        self.timestamp = datetime.now(UTC)

    def __str__(self):
        if self.context:
            return f"{self.message} (Context: {_scrub(self.context)})"
        return self.message

    def to_dict(self) -> dict:
        return {
            "error_code": self.error_code,
            "message": _scrub(self.message),
            "context": _scrub(self.context),
            "timestamp": self.timestamp.isoformat(),
            "status_code": self.default_status_code,
        }


class ConfigValidationError(BaseGiljoError):
    pass


class TemplateNotFoundError(BaseGiljoError):

    default_status_code: int = 404


class OrchestrationError(BaseGiljoError):

    default_status_code: int = 500


class ProjectStateError(OrchestrationError):

    default_status_code: int = 409


class CloseoutRequiredError(OrchestrationError):

    default_status_code: int = 409

    def __init__(self, message: str, blockers: list[dict], context: dict | None = None):
        super().__init__(message=message, context=context)
        self.blockers = blockers


class ImplementationNotReadyError(OrchestrationError):

    default_status_code: int = 404

    def __init__(self, reason: str, message: str, context: dict | None = None):
        super().__init__(message=message, context=context)
        self.reason = reason


class DatabaseError(BaseGiljoError):

    default_status_code: int = 500


class ValidationError(BaseGiljoError):

    default_status_code: int = 400


class CodedRefusalError(ValidationError):

    code = "REFUSED"

    products: list[dict] | None = None

    def as_refusal(self) -> dict[str, object]:
        payload: dict[str, object] = {"success": False, "error": self.code, "message": self.message}
        return payload if self.products is None else {**payload, "products": self.products}


class CrewNamingExhaustedError(CodedRefusalError):

    code = "CREW_NAMING_EXHAUSTED"


class AuthenticationError(BaseGiljoError):

    default_status_code: int = 401


class AuthorizationError(BaseGiljoError):

    default_status_code: int = 403


class ResourceNotFoundError(BaseGiljoError):

    default_status_code: int = 404


class AlreadyExistsError(BaseGiljoError):

    default_status_code: int = 409


class RetryExhaustedError(BaseGiljoError):
    pass


class ContextError(BaseGiljoError):
    pass


class GiljoFileNotFoundError(BaseGiljoError):
    pass
