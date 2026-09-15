# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from api.event_bus import EventBus
from giljo_mcp.events.schemas import EventFactory


logger = logging.getLogger(__name__)


class WebSocketEventListener:

    def __init__(self, event_bus: EventBus, ws_manager):
        self.event_bus = event_bus
        self.ws_manager = ws_manager
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def start(self) -> None:
        await self.event_bus.subscribe("project:mission_updated", self.handle_mission_updated)
        await self.event_bus.subscribe("agent:created", self.handle_agent_created)
        await self.event_bus.subscribe("product:status:changed", self.handle_product_status_changed)
        await self.event_bus.subscribe("template:updated", self.handle_template_updated)

        self.logger.info(
            "WebSocket event listener started",
            extra={
                "registered_events": [
                    "project:mission_updated",
                    "agent:created",
                    "product:status:changed",
                    "template:updated",
                ],
            },
        )

    async def handle_product_status_changed(self, data: dict[str, Any]) -> None:
        try:
            tenant_key = data.get("tenant_key")
            product_id = data.get("product_id")
            is_active = bool(data.get("is_active", False))

            if not tenant_key or not product_id:
                self.logger.error(
                    "Missing required fields for product status change",
                    extra={"data": data},
                )
                return

            event = EventFactory.tenant_envelope(
                event_type="product:status:changed",
                tenant_key=tenant_key,
                data={
                    "product_id": product_id,
                    "is_active": is_active,
                },
            )

            sent_count = await self.ws_manager.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)
            self.logger.info(
                f"Product status broadcasted to {sent_count} client(s)",
                extra={"product_id": product_id, "tenant_key": tenant_key, "sent_count": sent_count},
            )

        except Exception as e:
            self.logger.error(
                f"Error handling product status change event: {e}",
                extra={"error": str(e)},
                exc_info=True,
            )

    async def handle_mission_updated(self, data: dict[str, Any]) -> None:
        try:
            tenant_key = data.get("tenant_key")
            project_id = data.get("project_id")

            if not tenant_key or not project_id:
                self.logger.error(
                    "Missing required fields for mission update",
                    extra={"data": data},
                )
                return

            event = EventFactory.project_mission_updated(
                project_id=project_id,
                tenant_key=tenant_key,
                mission=data.get("mission", ""),
                user_config_applied=data.get("user_config_applied", False),
            )

            sent_count = await self.ws_manager.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)
            self.logger.info(
                f"Mission update broadcasted to {sent_count} client(s)",
                extra={
                    "project_id": project_id,
                    "tenant_key": tenant_key,
                    "sent_count": sent_count,
                },
            )

        except Exception as e:
            self.logger.error(
                f"Error handling mission update event: {e}",
                extra={"error": str(e)},
                exc_info=True,
            )

    async def handle_template_updated(self, data: dict[str, Any]) -> None:
        try:
            tenant_key = data.get("tenant_key")
            template_id = data.get("template_id")

            if not tenant_key or not template_id:
                self.logger.error(
                    "Missing required fields for template update",
                    extra={"data": data},
                )
                return

            event = EventFactory.tenant_envelope(
                event_type="template:updated",
                tenant_key=tenant_key,
                data={
                    "template_id": template_id,
                    "is_active": data.get("is_active"),
                    "updated_fields": data.get("updated_fields", []),
                },
            )

            sent_count = await self.ws_manager.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)
            self.logger.info(
                f"Template update broadcasted to {sent_count} client(s)",
                extra={"template_id": template_id, "tenant_key": tenant_key, "sent_count": sent_count},
            )

        except Exception as e:
            self.logger.error(
                f"Error handling template update event: {e}",
                extra={"error": str(e)},
                exc_info=True,
            )

    async def handle_agent_created(self, data: dict[str, Any]) -> None:
        try:
            tenant_key = data.get("tenant_key")
            project_id = data.get("project_id")
            agent_id = data.get("job_id")

            if not tenant_key or not project_id or not agent_id:
                self.logger.error(
                    "Missing required fields for agent creation",
                    extra={"data": data},
                )
                return

            event = EventFactory.agent_created(
                project_id=project_id,
                tenant_key=tenant_key,
                agent={
                    "id": agent_id,
                    "job_id": agent_id,
                    "agent_display_name": data.get("agent_display_name", "unknown"),
                    "agent_name": data.get("agent_name", "Unknown Agent"),
                    "status": data.get("status", "pending"),
                    "thin_client": data.get("thin_client", True),
                },
            )

            sent_count = await self.ws_manager.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)
            self.logger.info(
                f"Agent creation broadcasted to {sent_count} client(s)",
                extra={
                    "agent_id": agent_id,
                    "project_id": project_id,
                    "tenant_key": tenant_key,
                    "sent_count": sent_count,
                },
            )

        except Exception as e:
            self.logger.error(
                f"Error handling agent creation event: {e}",
                extra={"error": str(e)},
                exc_info=True,
            )
