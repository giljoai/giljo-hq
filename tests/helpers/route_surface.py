# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any


def iter_effective_routes(routes: Iterable[Any]) -> Iterator[Any]:
    for route in routes:
        candidates = getattr(route, "effective_candidates", None)
        if callable(candidates):
            yield from iter_effective_routes(candidates())
        elif getattr(route, "path", None) is not None:
            yield route


def route_signatures(routes: Iterable[Any]) -> set[tuple[str, frozenset]]:
    return {
        (route.path, frozenset(getattr(route, "methods", None) or frozenset()))
        for route in iter_effective_routes(routes)
    }
