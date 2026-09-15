# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


HOUSE_BRAND = "GiljoAI"
PRODUCT_NAME = "Giljo HQ"
PRODUCT_SHORT = "Giljo HQ"
MCP_ALIAS = "giljo_hq"
DESCRIPTOR = "Giljo HQ — project, task, and agent coordination for the one-person software company"

DIST_SLUG = MCP_ALIAS.replace("_", "-")

TWO_HUB_DISAMBIGUATION = (
    "This is Giljo HQ's built-in message hub; if another Giljo message-hub "
    "server (e.g. giljo_amh) is also connected in this session, ask the user "
    "which hub to use before posting."
)
