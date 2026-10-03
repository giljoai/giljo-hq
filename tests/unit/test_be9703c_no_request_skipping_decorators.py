# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import api.middleware
from api.middleware import csrf, rate_limiter


def test_the_unused_skipping_decorators_are_gone():
    for module in (api.middleware, csrf, rate_limiter):
        assert not hasattr(module, "CSRFProtectionOptional")
        assert not hasattr(module, "EndpointRateLimiter")
