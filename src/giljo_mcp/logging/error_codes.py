# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from enum import StrEnum


class ErrorCode(StrEnum):


    AUTH_INVALID_CREDENTIALS = "AUTH001"
    AUTH_TOKEN_EXPIRED = "AUTH002"
    AUTH_TOKEN_INVALID = "AUTH003"
    AUTH_UNAUTHORIZED = "AUTH004"
    AUTH_SESSION_EXPIRED = "AUTH005"
    AUTH_PIN_INVALID = "AUTH006"
    AUTH_PIN_EXPIRED = "AUTH007"
    AUTH_RATE_LIMIT_EXCEEDED = "AUTH008"
    AUTH_USER_NOT_FOUND = "AUTH009"
    AUTH_TENANT_MISMATCH = "AUTH010"
    AUTH_CSRF_VALIDATION_FAILED = "AUTH011"


    DB_CONNECTION_FAILED = "DB001"
    DB_QUERY_TIMEOUT = "DB002"
    DB_TRANSACTION_ROLLBACK = "DB003"
    DB_CONSTRAINT_VIOLATION = "DB004"
    DB_RECORD_NOT_FOUND = "DB005"
    DB_DUPLICATE_ENTRY = "DB006"
    DB_MIGRATION_FAILED = "DB007"
    DB_POOL_EXHAUSTED = "DB008"
    DB_DEADLOCK_DETECTED = "DB009"
    DB_INTEGRITY_ERROR = "DB010"


    WS_CONNECTION_FAILED = "WS001"
    WS_MESSAGE_SEND_FAILED = "WS002"
    WS_MESSAGE_PARSE_FAILED = "WS003"
    WS_AUTHENTICATION_FAILED = "WS004"
    WS_TENANT_ISOLATION_VIOLATED = "WS005"
    WS_BROADCAST_FAILED = "WS006"
    WS_DISCONNECTED_UNEXPECTEDLY = "WS007"
    WS_SUBSCRIPTION_FAILED = "WS008"
    WS_HEARTBEAT_TIMEOUT = "WS009"


    MCP_TOOL_EXECUTION_ERROR = "MCP001"
    MCP_AGENT_SPAWN_FAILED = "MCP002"
    MCP_CONTEXT_FETCH_FAILED = "MCP003"
    MCP_MISSION_NOT_FOUND = "MCP004"
    MCP_ORCHESTRATOR_ERROR = "MCP005"
    MCP_SUCCESSION_FAILED = "MCP006"
    MCP_AGENT_NOT_FOUND = "MCP007"
    MCP_INVALID_TENANT = "MCP008"
    MCP_TOOL_SCHEMA_INVALID = "MCP009"
    MCP_SESSION_EXPIRED = "MCP010"
    MCP_HTTP_TRANSPORT_ERROR = "MCP011"


    API_VALIDATION_ERROR = "API001"
    API_RATE_LIMIT_EXCEEDED = "API002"
    API_RESOURCE_NOT_FOUND = "API003"
    API_METHOD_NOT_ALLOWED = "API004"
    API_INTERNAL_ERROR = "API005"
    API_BAD_REQUEST = "API006"
    API_TIMEOUT = "API007"
    API_PAYLOAD_TOO_LARGE = "API008"
    API_UNSUPPORTED_MEDIA_TYPE = "API009"
    API_CONFLICT = "API010"
    API_DEPENDENCY_FAILED = "API011"

    def __str__(self) -> str:
        return self.value


ERROR_CODE_DESCRIPTIONS = {
    ErrorCode.AUTH_INVALID_CREDENTIALS: "Invalid username or password",
    ErrorCode.AUTH_TOKEN_EXPIRED: "JWT token has expired",
    ErrorCode.AUTH_TOKEN_INVALID: "JWT token is malformed or invalid",
    ErrorCode.AUTH_UNAUTHORIZED: "User not authorized for this resource",
    ErrorCode.AUTH_SESSION_EXPIRED: "User session has expired",
    ErrorCode.AUTH_PIN_INVALID: "Password recovery PIN is invalid",
    ErrorCode.AUTH_PIN_EXPIRED: "Password recovery PIN has expired",
    ErrorCode.AUTH_RATE_LIMIT_EXCEEDED: "Too many authentication attempts",
    ErrorCode.AUTH_USER_NOT_FOUND: "User account not found",
    ErrorCode.AUTH_TENANT_MISMATCH: "Tenant isolation violation detected",
    ErrorCode.AUTH_CSRF_VALIDATION_FAILED: "CSRF token validation failed",
    ErrorCode.DB_CONNECTION_FAILED: "Failed to connect to database",
    ErrorCode.DB_QUERY_TIMEOUT: "Database query execution timeout",
    ErrorCode.DB_TRANSACTION_ROLLBACK: "Database transaction rolled back",
    ErrorCode.DB_CONSTRAINT_VIOLATION: "Database constraint violation",
    ErrorCode.DB_RECORD_NOT_FOUND: "Requested database record not found",
    ErrorCode.DB_DUPLICATE_ENTRY: "Duplicate entry in database",
    ErrorCode.DB_MIGRATION_FAILED: "Database migration failed",
    ErrorCode.DB_POOL_EXHAUSTED: "Database connection pool exhausted",
    ErrorCode.DB_DEADLOCK_DETECTED: "Database deadlock detected",
    ErrorCode.DB_INTEGRITY_ERROR: "Data integrity violation",
    ErrorCode.WS_CONNECTION_FAILED: "WebSocket connection failed",
    ErrorCode.WS_MESSAGE_SEND_FAILED: "Failed to send WebSocket message",
    ErrorCode.WS_MESSAGE_PARSE_FAILED: "Failed to parse WebSocket message",
    ErrorCode.WS_AUTHENTICATION_FAILED: "WebSocket authentication failed",
    ErrorCode.WS_TENANT_ISOLATION_VIOLATED: "Cross-tenant WebSocket message attempt",
    ErrorCode.WS_BROADCAST_FAILED: "Failed to broadcast to tenant",
    ErrorCode.WS_DISCONNECTED_UNEXPECTEDLY: "Client disconnected unexpectedly",
    ErrorCode.WS_SUBSCRIPTION_FAILED: "Failed to subscribe to events",
    ErrorCode.WS_HEARTBEAT_TIMEOUT: "Client heartbeat timeout",
    ErrorCode.MCP_TOOL_EXECUTION_ERROR: "MCP tool execution failed",
    ErrorCode.MCP_AGENT_SPAWN_FAILED: "Failed to spawn MCP agent job",
    ErrorCode.MCP_CONTEXT_FETCH_FAILED: "Failed to fetch context via MCP",
    ErrorCode.MCP_MISSION_NOT_FOUND: "Agent mission not found",
    ErrorCode.MCP_ORCHESTRATOR_ERROR: "Orchestrator execution error",
    ErrorCode.MCP_SUCCESSION_FAILED: "Orchestrator succession failed",
    ErrorCode.MCP_AGENT_NOT_FOUND: "Agent job not found",
    ErrorCode.MCP_INVALID_TENANT: "Invalid tenant_key for MCP operation",
    ErrorCode.MCP_TOOL_SCHEMA_INVALID: "MCP tool schema validation failed",
    ErrorCode.MCP_SESSION_EXPIRED: "MCP session expired",
    ErrorCode.MCP_HTTP_TRANSPORT_ERROR: "MCP-over-HTTP transport error",
    ErrorCode.API_VALIDATION_ERROR: "Request validation failed",
    ErrorCode.API_RATE_LIMIT_EXCEEDED: "API rate limit exceeded",
    ErrorCode.API_RESOURCE_NOT_FOUND: "Requested resource not found",
    ErrorCode.API_METHOD_NOT_ALLOWED: "HTTP method not allowed",
    ErrorCode.API_INTERNAL_ERROR: "Internal server error",
    ErrorCode.API_BAD_REQUEST: "Malformed request",
    ErrorCode.API_TIMEOUT: "Request timeout",
    ErrorCode.API_PAYLOAD_TOO_LARGE: "Request payload too large",
    ErrorCode.API_UNSUPPORTED_MEDIA_TYPE: "Unsupported media type",
    ErrorCode.API_CONFLICT: "Resource conflict",
    ErrorCode.API_DEPENDENCY_FAILED: "External service dependency failed",
}


def get_error_description(error_code: ErrorCode) -> str:
    return ERROR_CODE_DESCRIPTIONS.get(error_code, "Unknown error")
