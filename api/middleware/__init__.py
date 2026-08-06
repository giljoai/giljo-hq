# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Middleware for Giljo HQ

This module provides security middleware:

- AuthMiddleware: Authentication for all API requests
- APIMetricsMiddleware: API and MCP call tracking
- SecurityHeadersMiddleware: Security headers (HSTS, CSP, X-Frame-Options, etc.)
- RateLimitMiddleware: Per-IP rate limiting (100 req/min default)
- InputValidationMiddleware: Input validation and sanitization
- CSRFProtectionMiddleware: CSRF protection

Created/Updated in Handover 0129c - Security Hardening & OWASP Compliance
"""

from .auth import AuthMiddleware
from .auth_rate_limiter import RateLimiter as AuthRateLimiter
from .auth_rate_limiter import get_rate_limiter
from .csrf import CSRFProtectionMiddleware, CSRFProtectionOptional, get_csrf_token
from .input_validator import InputValidationMiddleware, RequestSanitizer, sanitize
from .metrics import APIMetricsMiddleware
from .rate_limiter import EndpointRateLimiter, RateLimiter, RateLimitMiddleware
from .security import SecurityHeadersMiddleware


__all__ = [
    "APIMetricsMiddleware",
    "AuthMiddleware",
    "AuthRateLimiter",
    "CSRFProtectionMiddleware",
    "CSRFProtectionOptional",
    "EndpointRateLimiter",
    "InputValidationMiddleware",
    "RateLimitMiddleware",
    "RateLimiter",
    "RequestSanitizer",
    "SecurityHeadersMiddleware",
    "get_csrf_token",
    "get_rate_limiter",
    "sanitize",
]
