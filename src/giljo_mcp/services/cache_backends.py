# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


logger = logging.getLogger(__name__)


OAUTH_IDEMPOTENCY_BACKEND_NAME = "oauth_idempotency"
OAUTH_REFRESH_BACKEND_NAME = "oauth_refresh"

AUTH_RATE_LIMIT_BACKEND_NAME = "auth_rate_limiter"

GLOBAL_RATE_LIMIT_BACKEND_NAME = "global_rate_limiter"

LICENSE_CACHE_BACKEND_NAME = "license_cache"


@runtime_checkable
class CacheBackend(Protocol):

    async def get(self, tenant_key: str, key: str) -> str | None:
        ...

    async def set(self, tenant_key: str, key: str, value: str, *, ttl_seconds: int) -> None:
        ...

    async def setnx(self, tenant_key: str, key: str, value: str, *, ttl_seconds: int) -> bool:
        ...

    async def delete(self, tenant_key: str, key: str) -> None:
        ...

    async def incr(self, tenant_key: str, key: str, *, ttl_seconds: int) -> int:
        ...


@dataclass(slots=True)
class _DictEntry:
    value: str
    expires_at: datetime


@dataclass
class InProcessDictBackend:

    namespace: str
    max_entries: int = 1000
    _store: dict[str, _DictEntry] = field(default_factory=dict, init=False, repr=False)

    def _storage_key(self, tenant_key: str, key: str) -> str:
        return f"{self.namespace}:{tenant_key}:{key}"

    def _evict_if_full(self, target_key: str) -> None:
        if len(self._store) < self.max_entries or target_key in self._store:
            return
        oldest_key = min(self._store, key=lambda k: self._store[k].expires_at)
        self._store.pop(oldest_key, None)

    async def get(self, tenant_key: str, key: str) -> str | None:
        storage_key = self._storage_key(tenant_key, key)
        entry = self._store.get(storage_key)
        if entry is None:
            return None
        if entry.expires_at <= datetime.now(UTC):
            self._store.pop(storage_key, None)
            return None
        return entry.value

    async def set(self, tenant_key: str, key: str, value: str, *, ttl_seconds: int) -> None:
        storage_key = self._storage_key(tenant_key, key)
        self._evict_if_full(storage_key)
        self._store[storage_key] = _DictEntry(
            value=value,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )

    async def setnx(self, tenant_key: str, key: str, value: str, *, ttl_seconds: int) -> bool:
        storage_key = self._storage_key(tenant_key, key)
        existing = self._store.get(storage_key)
        if existing is not None and existing.expires_at > datetime.now(UTC):
            return False
        self._evict_if_full(storage_key)
        self._store[storage_key] = _DictEntry(
            value=value,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
        return True

    async def delete(self, tenant_key: str, key: str) -> None:
        self._store.pop(self._storage_key(tenant_key, key), None)

    async def incr(self, tenant_key: str, key: str, *, ttl_seconds: int) -> int:
        storage_key = self._storage_key(tenant_key, key)
        now = datetime.now(UTC)
        entry = self._store.get(storage_key)
        current = 0
        if entry is not None and entry.expires_at > now:
            try:
                current = int(entry.value)
            except (TypeError, ValueError):
                current = 0
        if current == 0:
            self._evict_if_full(storage_key)
            self._store[storage_key] = _DictEntry(
                value="1",
                expires_at=now + timedelta(seconds=ttl_seconds),
            )
            return 1
        count = current + 1
        entry.value = str(count)
        return count


_registry: dict[str, CacheBackend] = {}


def register_cache_backend(name: str, backend: CacheBackend) -> None:
    _registry[name] = backend
    logger.info("cache_backend_registered name=%s impl=%s", name, type(backend).__name__)


def get_cache_backend(name: str) -> CacheBackend:
    backend = _registry.get(name)
    if backend is None:
        backend = InProcessDictBackend(namespace=name)
        _registry[name] = backend
        logger.debug("cache_backend_default_created name=%s", name)
    return backend


def reset_registry_for_tests() -> None:
    _registry.clear()
