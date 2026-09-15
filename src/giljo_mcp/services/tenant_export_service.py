# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.events.schemas import EventFactory
from giljo_mcp.services.capture_tables import (
    ARTIFACT_SCHEMA_VERSION,
    capture_models,
    capture_table_names,
)
from giljo_mcp.tenant import TENANT_KEY_SHAPE


logger = logging.getLogger(__name__)



ALWAYS_STRIP: frozenset[str] = frozenset({"tenant_key"})

CREDENTIAL_STRIP: frozenset[str] = frozenset(
    {
        "password_hash",
        "recovery_pin_hash",
        "password_encrypted",
        "ssh_key_encrypted",
        "webhook_secret",
    }
)

PLATFORM_METADATA_STRIP: frozenset[str] = frozenset(
    {
        "customer_id",
        "subscription_id",
        "trial_status",
        "trial_started_at",
        "trial_expires_at",
    }
)

_ALL_STRIP_FIELDS: frozenset[str] = ALWAYS_STRIP | CREDENTIAL_STRIP | PLATFORM_METADATA_STRIP




_REDACTION_NOTICE = (
    "> NOTE: Password hashes, recovery PIN hashes, encrypted secrets, and "
    "webhook secrets were redacted from this export for security hygiene. "
    "Tenant-key values (`tk_...`) embedded in free-form text and JSONB "
    "content (mission strings, message bodies, memory entries, agent "
    "execution results) were also replaced with `<redacted-tenant-key>`. "
    "If you import this data into another tool, you will need to re-set "
    "credentials."
)


_TENANT_KEY_PATTERN = re.compile(TENANT_KEY_SHAPE.encode())
_TENANT_KEY_REDACTION = b"<redacted-tenant-key>"


def _redact_tenant_key_values(blob: bytes) -> bytes:
    return _TENANT_KEY_PATTERN.sub(_TENANT_KEY_REDACTION, blob)


_FIDELITY_NOTICE = (
    "> NOTE: This is a FIDELITY (operator / restore-grade) export. It is NOT "
    "redacted: tenant-key values, primary keys, foreign keys, password hashes, "
    "recovery PIN hashes, and encrypted secrets are all retained verbatim so a "
    "restore can faithfully reconstruct the tenant. TREAT THIS ARTIFACT AS A "
    "SECRET — store it encrypted at rest and never hand it to a data-subject "
    'as a "download my data" file (use the portability export for that).'
)


def _fidelity_restore_order() -> list[str]:
    return capture_table_names()


class TenantExportService:

    def __init__(
        self,
        db_session: AsyncSession,
        *,
        products_root: Path | None = None,
        websocket_manager: Any | None = None,
    ) -> None:
        self.db_session = db_session
        self.products_root = products_root or (Path.cwd() / "products")
        self.websocket_manager = websocket_manager


    async def export(self, *, tenant_key: str, fidelity: bool = False) -> tuple[Path, dict[str, int]]:
        if not tenant_key:
            raise ValueError("tenant_key is required")

        await self._set_repeatable_read()

        models = capture_models()
        model_data: dict[str, list[dict[str, Any]]] = {}
        model_counts: dict[str, int] = {}
        total = len(models)

        for idx, model in enumerate(models, start=1):
            name = model.__name__
            rows = await self._query_model_rows(model, tenant_key, fidelity=fidelity)
            model_data[name] = rows
            model_counts[name] = len(rows)
            await self._emit_progress(
                tenant_key=tenant_key,
                model=name,
                current=idx,
                total=total,
                records=len(rows),
                phase="exporting",
            )

        vision_entries = self._collect_vision_files(model_data.get("VisionDocument", []))

        zip_path = await asyncio.to_thread(
            self._write_zip,
            tenant_key=tenant_key,
            model_data=model_data,
            vision_entries=vision_entries,
            model_counts=model_counts,
            fidelity=fidelity,
        )

        await self._emit_progress(
            tenant_key=tenant_key,
            model="",
            current=total,
            total=total,
            records=sum(model_counts.values()),
            phase="complete",
        )
        return zip_path, model_counts


    async def _set_repeatable_read(self) -> None:
        conn = await self.db_session.connection()
        if conn.in_transaction():
            logger.debug("Session already in transaction; export at default isolation")
            return
        try:
            await self.db_session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        except Exception as exc:  # noqa: BLE001 — boundary, log + continue
            await self.db_session.rollback()
            logger.warning("Could not set REPEATABLE READ for export: %s", exc)


    async def _query_model_rows(self, model: type, tenant_key: str, *, fidelity: bool = False) -> list[dict[str, Any]]:
        columns = sa_inspect(model).columns
        column_names = [c.name for c in columns]
        if "tenant_key" not in column_names:
            logger.debug(
                "Skipping %s: no tenant_key column (would leak cross-tenant data)",
                model.__name__,
            )
            return []

        stmt = select(model).where(model.tenant_key == tenant_key)
        result = await self.db_session.execute(stmt)
        instances = result.scalars().all()
        return [self._serialize_row(inst, column_names, fidelity=fidelity) for inst in instances]

    @staticmethod
    def _serialize_row(instance: Any, column_names: list[str], *, fidelity: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for col_name in column_names:
            if not fidelity and col_name in _ALL_STRIP_FIELDS:
                continue
            value = getattr(instance, col_name, None)
            out[col_name] = _to_json_safe(value)
        if not fidelity:
            for stripped in _ALL_STRIP_FIELDS:
                out.pop(stripped, None)
        return out


    def _collect_vision_files(self, vision_rows: list[dict[str, Any]]) -> list[tuple[str, Path]]:
        entries: list[tuple[str, Path]] = []
        for row in vision_rows:
            vision_path = row.get("vision_path")
            product_id = row.get("product_id")
            storage_type = row.get("storage_type")
            if not vision_path or not product_id:
                continue
            if storage_type not in ("file", "hybrid"):
                continue
            src = Path(vision_path)
            if not src.is_absolute():
                src = self.products_root.parent / src if vision_path else src
            if not src.exists():
                logger.warning(
                    "Vision file referenced by VisionDocument id=%s does not exist on disk: %s",
                    row.get("id"),
                    vision_path,
                )
                continue
            zip_path = f"files/products/{product_id}/vision/{src.name}"
            entries.append((zip_path, src))
        return entries


    def _write_zip(
        self,
        *,
        tenant_key: str,
        model_data: dict[str, list[dict[str, Any]]],
        vision_entries: list[tuple[str, Path]],
        model_counts: dict[str, int],
        fidelity: bool = False,
    ) -> Path:
        tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115 — closed below
            mode="wb", suffix=".zip", delete=False
        )
        tmp.close()
        zip_path = Path(tmp.name)

        file_entries: list[dict[str, Any]] = []
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for model_name, rows in model_data.items():
                raw = json.dumps(rows, indent=2, sort_keys=True).encode("utf-8")
                blob = raw if fidelity else _redact_tenant_key_values(raw)
                arcname = f"data/{model_name}.json"
                zf.writestr(arcname, blob)
                file_entries.append(
                    {
                        "zip_path": arcname,
                        "sha256": hashlib.sha256(blob).hexdigest(),
                        "bytes": len(blob),
                    }
                )

            for arcname, src in vision_entries:
                data = src.read_bytes()
                zf.writestr(arcname, data)
                file_entries.append(
                    {
                        "zip_path": arcname,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "bytes": len(data),
                    }
                )

            schema_blob = self._build_schema_md(model_counts, fidelity=fidelity).encode("utf-8")
            zf.writestr("schema.md", schema_blob)
            file_entries.append(
                {
                    "zip_path": "schema.md",
                    "sha256": hashlib.sha256(schema_blob).hexdigest(),
                    "bytes": len(schema_blob),
                }
            )

            manifest = self._build_manifest(
                tenant_key=tenant_key,
                model_counts=model_counts,
                file_entries=file_entries,
                fidelity=fidelity,
            )
            manifest_blob = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
            zf.writestr("manifest.json", manifest_blob)

        return zip_path

    @staticmethod
    def _build_manifest(
        *,
        tenant_key: str,
        model_counts: dict[str, int],
        file_entries: list[dict[str, Any]],
        fidelity: bool = False,
    ) -> dict[str, Any]:
        from giljo_mcp import __version__ as _giljo_version

        try:
            from alembic.config import Config as AlembicConfig
            from alembic.script import ScriptDirectory

            cfg = AlembicConfig(str(Path.cwd() / "alembic.ini"))
            script = ScriptDirectory.from_config(cfg)
            head = script.get_current_head() or "unknown"
        except Exception:  # noqa: BLE001 — boundary, optional metadata
            head = "unknown"

        manifest: dict[str, Any] = {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "mode": "fidelity" if fidelity else "portability",
            "exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "tenant_key": tenant_key,
            "giljo_mcp_version": _giljo_version,
            "alembic_revision": head,
            "model_counts": model_counts,
            "models": {name: {"file": f"data/{name}.json", "count": count} for name, count in model_counts.items()},
            "files": file_entries,
        }
        if fidelity:
            manifest["restore_order"] = _fidelity_restore_order()
        return manifest

    @staticmethod
    def _build_schema_md(model_counts: dict[str, int], *, fidelity: bool = False) -> str:
        lines: list[str] = [
            "# Giljo HQ — Tenant Data Export",
            "",
            _FIDELITY_NOTICE if fidelity else _REDACTION_NOTICE,
            "",
            "## Contents",
            "",
            "One `data/<Model>.json` file per exported table. Vision documents",
            "are stored inline in `data/vision_documents.json` (BE-5115:",
            "file-based vision storage removed; the export ZIP no longer",
            "contains a separate `files/` tree for vision content).",
            "",
            "## Tables",
            "",
        ]
        descriptions = _TABLE_DESCRIPTIONS
        for name, count in sorted(model_counts.items()):
            blurb = descriptions.get(name, "Tenant-scoped table.")
            lines.append(f"### {name}  ({count} row{'s' if count != 1 else ''})")
            lines.append("")
            lines.append(blurb)
            lines.append("")
        return "\n".join(lines)


    async def _emit_progress(
        self,
        *,
        tenant_key: str,
        model: str,
        current: int,
        total: int,
        records: int,
        phase: str,
    ) -> None:
        if not self.websocket_manager:
            return
        try:
            event = EventFactory.tenant_envelope(
                event_type="tenant:export_progress",
                tenant_key=tenant_key,
                data={
                    "model": model,
                    "current": current,
                    "total": total,
                    "records": records,
                    "phase": phase,
                },
            )
            await self.websocket_manager.broadcast_event_to_tenant(tenant_key=tenant_key, event=event)
        except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as exc:
            logger.debug("export progress emit failed (non-blocking): %s", exc)




def _to_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None
    return str(value)



_TABLE_DESCRIPTIONS: dict[str, str] = {
    "Organization": "Tenant organization record.",
    "OrgMembership": "User -> organization membership rows.",
    "User": "User accounts. password_hash, recovery_pin_hash redacted.",
    "UserFieldPriority": "Per-user toggle of optional context categories.",
    "Settings": "Per-tenant settings blob.",
    "SetupState": "Installation state (one row per tenant).",
    "Configuration": "Tenant-scoped configuration entries.",
    "Product": "Top-level product entities.",
    "ProductTechStack": "Tech-stack rows joined 1:N to Product.",
    "ProductArchitecture": "Architecture description rows joined 1:N to Product.",
    "ProductTestConfig": "Test configuration rows joined 1:N to Product.",
    "VisionDocument": "Vision document metadata. Inline text + on-disk file path.",
    "TaxonomyType": "Project/task taxonomy rows.",
    "Project": "Projects (work orders for agents).",
    "ProductMemoryEntry": "360 memory entries scoped to a product.",
    "MCPContextIndex": "Chunked context index for RAG. searchable_vector excluded.",
    "CommThread": "Message Hub threads (subject, status, baton, resolution).",
    "CommParticipant": "Message Hub participant directory + per-thread read cursors.",
    "Task": "Tasks (work items, may be lifted from agent TODOs).",
    "Message": "Inter-agent messages.",
    "MessageRecipient": "Junction: messages -> recipient agents.",
    "MessageAcknowledgment": "Per-recipient ack timestamps for messages.",
    "MessageCompletion": "Per-recipient completion records for messages.",
    "AgentTemplate": "Customizable agent template definitions.",
    "TemplateArchive": "Soft-deleted / archived agent templates.",
    "ProductAgentAssignment": "Per-product enable/disable toggle for agent templates.",
    "AgentJob": "Spawned agent work orders.",
    "AgentExecution": "Per-job execution traces.",
    "AgentTodoItem": "Per-job TODO list items (the product feature, not source markers).",
    "UserApproval": "User approval gate records (BE-5029 awaiting_user flow).",
    "Roadmap": "Product roadmaps.",
    "RoadmapItem": "Roadmap entries (may link projects/tasks).",
    "SequenceRun": "Chain runs (linked multi-project executions).",
    "Notification": "In-app notifications.",
    "TenantSkillsAck": "Skills-onboarding acknowledgment state (one row per tenant).",
}
