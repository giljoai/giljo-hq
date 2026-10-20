# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from api.endpoints.mcp_sdk_server import _STREAMABLE_HTTP_KWARGS


def test_mcp_transport_stays_stateless():
    assert _STREAMABLE_HTTP_KWARGS["stateless_http"] is True
