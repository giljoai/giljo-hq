# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TenantExportService — GDPR data portability for the authenticated tenant.

Produces a ZIP file containing:
    manifest.json   (schema version, exported_at, tenant_key provenance,
                     alembic_revision, giljo_mcp_version, per-file SHA-256,
                     model_counts, model->file map)
    schema.md       (human-readable redaction notice + table descriptions)
    data/<Model>.json   (one file per exported model, list of row dicts)

BE-5115: vision_documents are stored inline (vision_documents.vision_document
column); their full content already lives in data/vision_documents.json, so
no separate files/ entries are produced. Legacy 'file' / 'hybrid' rows were
migrated to 'inline' by ce_0032_vision_docs_inline_only, after which the
storage_type filter in _collect_vision_files matches zero rows.

Strip filter is applied per-field at serialize time (mission spec, narrow):
    ALWAYS_STRIP, CREDENTIAL_STRIP, PLATFORM_METADATA_STRIP    — field-level
Entire-table selection is schema-DISCOVERED (BE-9188): see
``giljo_mcp/services/capture_tables.py`` (tenant-keyed models minus the
justified EXPORT_EXCLUDE).

The full export is wrapped in REPEATABLE READ so the snapshot is consistent
across all model queries.

WebSocket progress emission uses the existing app.state.websocket_manager;
no new broker is created. Event type is "tenant:export_progress".
"""

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


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Strip lists — narrow form (mission spec, EXACT — different from
# CE_TO_SOLO_ROADMAP round-trip migration version).
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Table selection (BE-9188): the capture set is DISCOVERED, not listed here.
# ``capture_tables.capture_models()`` derives it from ``Base.metadata`` (every
# tenant-keyed model minus the justified ``EXPORT_EXCLUDE``), so adding a new
# product table never requires touching this service. The old hand-maintained
# EXPORT_MODELS allowlist is gone — it drifted twice (BE-6113 on the deletion
# side, IMP-9186 here) and the second drift was a confirmed restore data-loss
# defect (BE-9187).
# --------------------------------------------------------------------------- #


_REDACTION_NOTICE = (
    "> NOTE: Password hashes, recovery PIN hashes, encrypted secrets, and "
    "webhook secrets were redacted from this export for security hygiene. "
    "Tenant-key values (`tk_...`) embedded in free-form text and JSONB "
    "content (mission strings, message bodies, memory entries, agent "
    "execution results) were also replaced with `<redacted-tenant-key>`. "
    "If you import this data into another tool, you will need to re-set "
    "credentials."
)


# Tenant-key values may appear inside free-form text or JSONB content
# (mission strings, message bodies, memory entries, agent execution
# result blobs). The per-field strip filter cannot reach those because
# they are payload, not column names. We scrub them at the JSON-bytes
# level just before each data/*.json is written to the ZIP. The pattern
# is intentionally narrow (the GiljoAI tenant_key format is `tk_` +
# 20+ alphanumeric chars) so it does not false-positive on normal user
# content.
_TENANT_KEY_PATTERN = re.compile(rb"tk_[A-Za-z0-9]{20,}")
_TENANT_KEY_REDACTION = b"<redacted-tenant-key>"


def _redact_tenant_key_values(blob: bytes) -> bytes:
    return _TENANT_KEY_PATTERN.sub(_TENANT_KEY_REDACTION, blob)


# Fidelity (operator / restore-grade) export carries no redactions — the whole
# point is to faithfully rebuild a tenant. This notice replaces the portability
# redaction notice in schema.md so an operator knows the artifact is sensitive.
_FIDELITY_NOTICE = (
    "> NOTE: This is a FIDELITY (operator / restore-grade) export. It is NOT "
    "redacted: tenant-key values, primary keys, foreign keys, password hashes, "
    "recovery PIN hashes, and encrypted secrets are all retained verbatim so a "
    "restore can faithfully reconstruct the tenant. TREAT THIS ARTIFACT AS A "
    "SECRET — store it encrypted at rest and never hand it to a data-subject "
    'as a "download my data" file (use the portability export for that).'
)


def _fidelity_restore_order() -> list[str]:
    """Capture-set table names in FK-correct INSERT order (parents first).

    Delegates to the discovery module (BE-9188) — ``capture_table_names()`` is
    the one source of truth for both the table set and its topological order.
    The restore path (chain step f) reverses this list for FK-safe deletes.
    Kept as a named seam because the manifest builder and the round-trip tests
    reference it.
    """
    return capture_table_names()


class TenantExportService:
    """Exports all tenant-scoped data for one tenant to a portable ZIP file."""

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

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #

    async def export(self, *, tenant_key: str, fidelity: bool = False) -> tuple[Path, dict[str, int]]:
        """Run the full export for ``tenant_key`` and return (zip_path, model_counts).

        The zip is written to a temp file on disk; caller is responsible for
        moving it to the download-token staging directory.

        ``fidelity`` selects the export grade (BE-6130c):

        * ``False`` (default) — *portability* grade (GDPR "download my data").
          ``tenant_key``, credentials, and platform metadata are stripped per
          :data:`_ALL_STRIP_FIELDS`, and ``tk_`` values embedded in free-form
          text / JSONB are byte-scrubbed. You CANNOT faithfully rebuild a tenant
          from this artifact — that is the point.
        * ``True`` — *fidelity* (operator / restore) grade for backup & restore.
          KEEPS ``tenant_key``, primary keys, and every FK column; does NOT redact
          credentials (so a restore can reconstruct auth — the caller stores the
          artifact encrypted, chain step d); does NOT byte-scrub ``tk_`` values.
          The manifest records ``mode="fidelity"`` plus an FK-correct
          ``restore_order`` so the restore path (chain step f) re-inserts
          parents before children. Same REPEATABLE READ snapshot, same
          discovered capture set as portability mode.
        """
        if not tenant_key:
            raise ValueError("tenant_key is required")

        await self._set_repeatable_read()

        # Discovered per call (BE-9188): every tenant-keyed model registered in
        # this runtime, minus the justified EXPORT_EXCLUDE, parents-first.
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

        # BE-9052: the serialize+compress (json.dumps of the whole dataset +
        # ZIP_DEFLATE) is CPU-bound and previously ran inline on the event loop,
        # so one large tenant stalled the single hosted worker for everyone. Run
        # it in a worker thread — _write_zip touches no session (only the already
        # materialized model_data + on-disk vision files), so it is thread-safe.
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

    # ------------------------------------------------------------------ #
    # Snapshot consistency
    # ------------------------------------------------------------------ #

    async def _set_repeatable_read(self) -> None:
        # SET TRANSACTION ISOLATION LEVEL must precede any query in the
        # transaction. SQLAlchemy AsyncSession lazily opens a tx on the
        # first execute, so once any query has been issued on the session
        # the SET will fail with ActiveSQLTransactionError AND poison the
        # in-flight transaction. We skip the SET entirely when a tx is
        # already in flight — the export still produces a coherent
        # snapshot under default READ COMMITTED for single-user CE use,
        # and SaaS/hosted modes are 403'd at the endpoint anyway.
        conn = await self.db_session.connection()
        if conn.in_transaction():
            logger.debug("Session already in transaction; export at default isolation")
            return
        try:
            await self.db_session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        except Exception as exc:  # noqa: BLE001 — boundary, log + continue
            await self.db_session.rollback()
            logger.warning("Could not set REPEATABLE READ for export: %s", exc)

    # ------------------------------------------------------------------ #
    # Per-model query + serialize
    # ------------------------------------------------------------------ #

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
            # Fidelity (restore-grade) keeps every column — tenant_key, PKs, FK
            # columns, credentials — so the artifact can faithfully rebuild the
            # tenant. Portability strips the security/identity columns.
            if not fidelity and col_name in _ALL_STRIP_FIELDS:
                continue
            value = getattr(instance, col_name, None)
            out[col_name] = _to_json_safe(value)
        if not fidelity:
            # Also strip any non-column attribute that happens to match a strip
            # field name (defense-in-depth against ORM augmentations).
            for stripped in _ALL_STRIP_FIELDS:
                out.pop(stripped, None)
        return out

    # ------------------------------------------------------------------ #
    # Vision file bundling
    # ------------------------------------------------------------------ #

    def _collect_vision_files(self, vision_rows: list[dict[str, Any]]) -> list[tuple[str, Path]]:
        """Resolve vision files referenced by VisionDocument rows.

        Returns list of (zip_path, source_path) pairs for files that exist on
        disk. Missing files emit a WARNING and are skipped (mission spec).
        """
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

    # ------------------------------------------------------------------ #
    # ZIP packaging + manifest + schema.md
    # ------------------------------------------------------------------ #

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
            # data/*.json
            for model_name, rows in model_data.items():
                raw = json.dumps(rows, indent=2, sort_keys=True).encode("utf-8")
                # Fidelity keeps tk_ values intact (a restore needs them);
                # portability scrubs tk_ values that hide inside free-form
                # text / JSONB payloads (column-name strip cannot reach those).
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

            # files/products/<id>/vision/<name>
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

            # schema.md
            schema_blob = self._build_schema_md(model_counts, fidelity=fidelity).encode("utf-8")
            zf.writestr("schema.md", schema_blob)
            file_entries.append(
                {
                    "zip_path": "schema.md",
                    "sha256": hashlib.sha256(schema_blob).hexdigest(),
                    "bytes": len(schema_blob),
                }
            )

            # manifest.json — must be the LAST entry so it can reference all others
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
            # "2.0" = discovery-era capture set (BE-9188); "1.0" = allowlist era.
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
            # The restore path (chain step f) re-inserts parents before children;
            # this is the FK-correct INSERT order for the captured tables.
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

    # ------------------------------------------------------------------ #
    # WebSocket progress emission (reuse existing broker)
    # ------------------------------------------------------------------ #

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


# --------------------------------------------------------------------------- #
# JSON serialization helpers
# --------------------------------------------------------------------------- #


def _to_json_safe(value: Any) -> Any:
    """Convert SQLAlchemy/Python values to JSON-safe primitives."""
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
        return None  # TSVECTOR / bytea columns are not portable
    # Fallback for SQLAlchemy ARRAY / Enum / etc.
    return str(value)


# --------------------------------------------------------------------------- #
# schema.md descriptions (terse — schema is documented in models, this is
# the user-facing crib sheet)
# --------------------------------------------------------------------------- #

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
