# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Giljo HQ API Package
FastAPI-based REST and WebSocket API for orchestration system

Note: `create_app` is intentionally NOT eagerly imported here. Importing it would
drag full FastAPI app construction (ConfigManager, DB wiring, JWT manager) into
every `api.*` submodule import — including pytest collection, where it explodes
before fixtures and the test DB exist. Import it explicitly from `api.app` instead.
See INF-5061.
"""
