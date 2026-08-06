# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
SEC-0005c security regression suites.

Two property suites guard the two-orthogonal-axes invariant established in
SEC-0005a/SEC-0005b:

- ``test_tenant_required`` (Property B): every TENANT-LEVEL admin-gated endpoint
  must carry a tenant gate -- either an in-handler ``_require_tenant``-style
  guard that 4xx's when ``current_user.tenant_key`` is null/empty, or a
  ``Depends(get_tenant_key)`` chain that injects the tenant from request state.

- ``test_ce_mode_required`` (Mode gate): every SERVER-LEVEL admin-gated endpoint
  must depend on ``require_ce_mode`` so that the route 404s in demo/SaaS modes.

The endpoint inventory is the lane (a)/(b) taxonomy in the SEC-0005c sweep
taxonomy. If a new admin-gated endpoint is
added, classify it in the taxonomy and add a row here.
"""
