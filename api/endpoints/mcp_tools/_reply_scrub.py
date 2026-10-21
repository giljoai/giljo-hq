# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from typing import Any


def scrub_tenant_key(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: scrub_tenant_key(v) for k, v in node.items() if k != "tenant_key"}
    if isinstance(node, list):
        return [scrub_tenant_key(v) for v in node]
    return node
