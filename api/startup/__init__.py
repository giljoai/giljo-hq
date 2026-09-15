# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from api.startup.background_tasks import init_background_tasks
from api.startup.core_services import init_core_services
from api.startup.database import init_database
from api.startup.event_bus import init_event_bus
from api.startup.health_monitor import init_health_monitor
from api.startup.shutdown import shutdown
from api.startup.silence_detector import init_silence_detector
from api.startup.validation import init_validation


__all__ = [
    "init_background_tasks",
    "init_core_services",
    "init_database",
    "init_event_bus",
    "init_health_monitor",
    "init_silence_detector",
    "init_validation",
    "shutdown",
]
