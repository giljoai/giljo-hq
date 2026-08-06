# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tenant Management System for Giljo HQ.

Provides tenant key generation, validation, and context management
for complete project isolation in multi-tenant environments.
"""

import hashlib
import secrets
import string
from contextvars import ContextVar, Token
from typing import Any, ClassVar


# Thread-safe context variable for current tenant
current_tenant: ContextVar[str | None] = ContextVar("current_tenant", default=None)


class TenantManager:
    """
    Manages tenant keys and context for multi-tenant isolation.

    Features:
    - Generates cryptographically secure tenant keys
    - Validates tenant key format and integrity
    - Manages tenant context across async operations
    - Provides tenant key inheritance for child entities
    """

    # Tenant key configuration
    KEY_LENGTH = 32  # 32 characters = 192 bits of entropy
    KEY_PREFIX = "tk_"  # Identifies tenant keys
    KEY_ALPHABET = string.ascii_letters + string.digits

    # Validation cache to avoid repeated checks
    _validation_cache: ClassVar[dict[str, bool]] = {}
    _cache_max_size: ClassVar[int] = 1000  # Limit cache size to prevent memory issues

    @classmethod
    def generate_tenant_key(cls, project_name: str | None = None) -> str:
        """
        Generate a unique, cryptographically secure tenant key.

        Args:
            project_name: Optional project name to include in key metadata

        Returns:
            A unique tenant key in format: tk_<32-char-random>
        """
        # Generate random component
        random_chars = "".join(secrets.choice(cls.KEY_ALPHABET) for _ in range(cls.KEY_LENGTH))

        tenant_key = f"{cls.KEY_PREFIX}{random_chars}"

        # Clear cache if it's getting too large
        if len(cls._validation_cache) > cls._cache_max_size:
            cls._validation_cache.clear()

        # Pre-validate the generated key
        cls._validation_cache[tenant_key] = True

        return tenant_key

    @classmethod
    def validate_tenant_key(cls, tenant_key: str | None) -> bool:
        """
        Validate tenant key format and structure.

        Args:
            tenant_key: The tenant key to validate

        Returns:
            True if valid, False otherwise
        """
        if not tenant_key:
            return False

        # Check cache first
        if tenant_key in cls._validation_cache:
            return cls._validation_cache[tenant_key]

        # Validate format
        is_valid = (
            isinstance(tenant_key, str)
            and tenant_key.startswith(cls.KEY_PREFIX)
            and len(tenant_key) == len(cls.KEY_PREFIX) + cls.KEY_LENGTH
            and all(c in cls.KEY_ALPHABET for c in tenant_key[len(cls.KEY_PREFIX) :])
        )

        # Cache result
        if len(cls._validation_cache) < cls._cache_max_size:
            cls._validation_cache[tenant_key] = is_valid

        return is_valid

    @classmethod
    def set_current_tenant(cls, tenant_key: str) -> Token[str | None]:
        """
        Set the current tenant context.

        Args:
            tenant_key: The tenant key to set as current

        Returns:
            The ``contextvars.Token`` for this set. Pass it to
            ``current_tenant.reset(token)`` to restore the exact prior value
            (leak-proof unwinding). Callers that perform a genuine hard-clear
            instead of an unwind may ignore the token and call
            ``clear_current_tenant()``.

        Raises:
            ValueError: If tenant_key is invalid
        """
        if not cls.validate_tenant_key(tenant_key):
            raise ValueError(f"Invalid tenant key: {tenant_key}")

        return current_tenant.set(tenant_key)

    @classmethod
    def get_current_tenant(cls) -> str | None:
        """
        Get the current tenant from context.

        Returns:
            Current tenant key or None if not set
        """
        return current_tenant.get()

    @classmethod
    def clear_current_tenant(cls) -> None:
        """
        Hard-clear the current tenant context to None.

        This is a no-arg HARD clear for genuine terminal clears where there is
        no prior value to unwind to (e.g. the end of a cross-tenant background
        maintenance loop, or forcing a known-clean baseline in a test).

        For request/context lifecycles that must restore the EXACT prior value,
        do NOT use this — capture the token returned by ``set_current_tenant``
        and call ``current_tenant.reset(token)`` instead. Using ``set(None)``
        to "restore" would clobber any tenant a caller higher in the stack had
        set, which is the cross-tenant leak this slice (BE6004C-1) closes.
        """
        current_tenant.set(None)

    @classmethod
    def require_tenant(cls) -> str:
        """
        Get current tenant, raising error if not set.

        Returns:
            Current tenant key

        Raises:
            RuntimeError: If no tenant context is set
        """
        tenant_key = cls.get_current_tenant()
        if not tenant_key:
            raise RuntimeError("No tenant context set. Call set_current_tenant() first.")
        return tenant_key

    @classmethod
    def with_tenant(cls, tenant_key: str):
        """
        Context manager for temporary tenant context.

        Usage:
            with TenantManager.with_tenant("tk_abc123..."):
                # Operations use this tenant context
                pass
        """

        class TenantContext:
            def __init__(self, key: str):
                self.key = key
                self._token: Token[str | None] | None = None

            def __enter__(self):
                # Capture the token from the set so __exit__ can reset to the
                # EXACT prior value (incl. None), making nested contexts unwind
                # correctly even when an outer tenant is already active.
                self._token = TenantManager.set_current_tenant(self.key)
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                if self._token is not None:
                    current_tenant.reset(self._token)
                    self._token = None

        return TenantContext(tenant_key)

    @classmethod
    def hash_tenant_key(cls, tenant_key: str) -> str:
        """
        Create a hash of the tenant key for logging/debugging.
        Never log raw tenant keys!

        Args:
            tenant_key: The tenant key to hash

        Returns:
            SHA-256 hash prefix (first 8 chars) for identification
        """
        if not tenant_key:
            return "no_tenant"

        hash_obj = hashlib.sha256(tenant_key.encode())
        return hash_obj.hexdigest()[:8]

    @classmethod
    def apply_tenant_filter(cls, query: Any, model: Any, tenant_key: str | None = None) -> Any:
        """
        Apply tenant filtering to a SQLAlchemy query.

        Args:
            query: SQLAlchemy query object
            model: Model class being queried
            tenant_key: Specific tenant key or None to use current context

        Returns:
            Query with tenant filter applied

        Raises:
            ValueError: If no tenant key available (explicit or from context)
        """
        # Determine which tenant key to use
        key_to_use = tenant_key or cls.get_current_tenant()

        if not key_to_use:
            raise ValueError(
                "apply_tenant_filter called without tenant_key and no tenant context set. "
                "Pass tenant_key explicitly or set tenant context via set_current_tenant()."
            )

        if hasattr(model, "tenant_key"):
            return query.filter(model.tenant_key == key_to_use)

        return query

    @classmethod
    def ensure_tenant_isolation(cls, entity: Any, tenant_key: str | None = None) -> None:
        """
        Ensure entity belongs to the correct tenant.

        Args:
            entity: Entity to check
            tenant_key: Expected tenant key (uses current context if None)

        Raises:
            ValueError: If no tenant key available (explicit or from context)
            PermissionError: If entity belongs to different tenant
        """
        if not hasattr(entity, "tenant_key"):
            return  # Entity doesn't support multi-tenancy

        expected_key = tenant_key or cls.get_current_tenant()
        if not expected_key:
            raise ValueError(
                "ensure_tenant_isolation called without tenant_key and no tenant context set. "
                "Pass tenant_key explicitly or set tenant context via set_current_tenant()."
            )

        if entity.tenant_key != expected_key:
            raise PermissionError(
                f"Access denied: Entity belongs to different tenant. "
                f"Expected: {cls.hash_tenant_key(expected_key)}, "
                f"Got: {cls.hash_tenant_key(entity.tenant_key)}"
            )


# Convenience functions for common operations
def generate_tenant_key(project_name: str | None = None) -> str:
    """Convenience function to generate a tenant key."""
    return TenantManager.generate_tenant_key(project_name)


def validate_tenant_key(tenant_key: str | None) -> bool:
    """Convenience function to validate a tenant key."""
    return TenantManager.validate_tenant_key(tenant_key)


def get_current_tenant() -> str | None:
    """Convenience function to get current tenant."""
    return TenantManager.get_current_tenant()


def set_current_tenant(tenant_key: str) -> Token[str | None]:
    """Convenience function to set current tenant.

    Returns the ``contextvars.Token`` for the set; pass it to
    ``current_tenant.reset(token)`` to restore the exact prior value.
    """
    return TenantManager.set_current_tenant(tenant_key)


def clear_current_tenant() -> None:
    """Convenience function to hard-clear the current tenant context to None.

    See ``TenantManager.clear_current_tenant`` — this is a terminal hard clear,
    not an unwind. For lifecycle restore use the token from
    ``set_current_tenant`` with ``current_tenant.reset(token)``.
    """
    TenantManager.clear_current_tenant()


def with_tenant(tenant_key: str):
    """Convenience function for tenant context manager."""
    return TenantManager.with_tenant(tenant_key)
