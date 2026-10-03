# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import hashlib
import secrets
import string
from contextvars import ContextVar, Token
from typing import Any, ClassVar


current_tenant: ContextVar[str | None] = ContextVar("current_tenant", default=None)


TENANT_KEY_SHAPE = r"tk_[A-Za-z0-9]{20,}"


class TenantManager:

    KEY_LENGTH = 32
    KEY_PREFIX = "tk_"
    KEY_ALPHABET = string.ascii_letters + string.digits

    _validation_cache: ClassVar[dict[str, bool]] = {}
    _cache_max_size: ClassVar[int] = 1000

    @classmethod
    def generate_tenant_key(cls, project_name: str | None = None) -> str:
        random_chars = "".join(secrets.choice(cls.KEY_ALPHABET) for _ in range(cls.KEY_LENGTH))

        tenant_key = f"{cls.KEY_PREFIX}{random_chars}"

        if len(cls._validation_cache) > cls._cache_max_size:
            cls._validation_cache.clear()

        cls._validation_cache[tenant_key] = True

        return tenant_key

    @classmethod
    def validate_tenant_key(cls, tenant_key: str | None) -> bool:
        if not tenant_key:
            return False

        if tenant_key in cls._validation_cache:
            return cls._validation_cache[tenant_key]

        is_valid = (
            isinstance(tenant_key, str)
            and tenant_key.startswith(cls.KEY_PREFIX)
            and len(tenant_key) == len(cls.KEY_PREFIX) + cls.KEY_LENGTH
            and all(c in cls.KEY_ALPHABET for c in tenant_key[len(cls.KEY_PREFIX) :])
        )

        if len(cls._validation_cache) < cls._cache_max_size:
            cls._validation_cache[tenant_key] = is_valid

        return is_valid

    @classmethod
    def set_current_tenant(cls, tenant_key: str) -> Token[str | None]:
        if not cls.validate_tenant_key(tenant_key):
            raise ValueError(f"Invalid tenant key: {tenant_key}")

        return current_tenant.set(tenant_key)

    @classmethod
    def get_current_tenant(cls) -> str | None:
        return current_tenant.get()

    @classmethod
    def clear_current_tenant(cls) -> None:
        current_tenant.set(None)

    @classmethod
    def require_tenant(cls) -> str:
        tenant_key = cls.get_current_tenant()
        if not tenant_key:
            raise RuntimeError("No tenant context set. Call set_current_tenant() first.")
        return tenant_key

    @classmethod
    def with_tenant(cls, tenant_key: str):

        class TenantContext:
            def __init__(self, key: str):
                self.key = key
                self._token: Token[str | None] | None = None

            def __enter__(self):
                self._token = TenantManager.set_current_tenant(self.key)
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                if self._token is not None:
                    current_tenant.reset(self._token)
                    self._token = None

        return TenantContext(tenant_key)

    @classmethod
    def hash_tenant_key(cls, tenant_key: str) -> str:
        if not tenant_key:
            return "no_tenant"

        hash_obj = hashlib.sha256(tenant_key.encode())
        return hash_obj.hexdigest()[:8]

    @classmethod
    def apply_tenant_filter(cls, query: Any, model: Any, tenant_key: str | None = None) -> Any:
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
        if not hasattr(entity, "tenant_key"):
            return

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


def generate_tenant_key(project_name: str | None = None) -> str:
    return TenantManager.generate_tenant_key(project_name)


def get_current_tenant() -> str | None:
    return TenantManager.get_current_tenant()


def set_current_tenant(tenant_key: str) -> Token[str | None]:
    return TenantManager.set_current_tenant(tenant_key)


def clear_current_tenant() -> None:
    TenantManager.clear_current_tenant()


def with_tenant(tenant_key: str):
    return TenantManager.with_tenant(tenant_key)
