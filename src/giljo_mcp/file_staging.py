# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
File Staging for one-time download token system.

Handover 0100: Temporary file staging for secure downloads.

Features:
- Staging directory creation (temp/{tenant_key}/{token}/)
- ZIP file generation for slash commands and agent templates
- Metadata JSON persistence
- Cleanup after download
- Directory traversal protection

Usage:
    staging = FileStaging(base_path=Path("temp"), db_session=db_session)

    # Create staging path
    staging_path = await staging.create_staging_directory(tenant_key, token)

    # Stage slash commands (platform: claude_code, gemini_cli, codex_cli)
    zip_path, msg = await staging.stage_slash_commands(staging_path, platform="claude_code")

    # Stage agent templates (platform: claude_code, gemini_cli, codex_cli)
    zip_path, msg = await staging.stage_agent_templates(staging_path, tenant_key, db_session, platform="claude_code")

    # Cleanup
    await staging.cleanup(tenant_key, token)
"""

import logging
import re
import shutil
import zipfile
from datetime import UTC
from json import dumps as json_dumps
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import tenant_session_context
from .models import AgentTemplate, DownloadToken
from .platform_registry import EXPORT_ANTIGRAVITY_CLI, EXPORT_CODEX_CLI, SKILL_SLASH_PLATFORMS
from .tools.slash_command_templates import get_all_templates


logger = logging.getLogger(__name__)


# Template-bearing ZIPs are rendered from the tenant's agent templates.
# slash_commands.zip is static content and can never go stale, so it is excluded.
_TEMPLATE_BEARING_ZIPS = frozenset({"agent_templates.zip", "giljo_setup.zip"})


async def staged_agent_zip_is_stale(session: AsyncSession, tenant_key: str, filename: str, token: str) -> bool:
    """True if a template-bearing staged ZIP would serve a pre-change snapshot (BE-9208 D1).

    The token download endpoint serves the ZIP bytes frozen at staging time; we refuse
    to serve one older than the tenant's latest template write. Compared over the
    tenant's templates:
      content_watermark = MAX(COALESCE(updated_at, created_at))  # latest create/edit/toggle/delete

    TSK-9210: the baseline is THIS token's own ``staged_at`` (stamped in
    ``TokenManager.mark_ready()``, which runs after staging commits
    ``last_exported_at``). BE-9208 originally compared against the tenant-global
    export watermark ``MAX(last_exported_at)``, which two overlapping tokens can
    defeat: token A staged, template edited, token B staged -> B's staging pushes the
    export watermark past the edit, so A's genuinely-stale link reads as fresh and is
    served 200. Anchoring per token removes the masking, because A is judged against
    A's staging time.

    NB: anchoring on ``token.created_at`` instead would false-positive on EVERY fresh
    download — the staging ``last_exported_at`` write bumps ``updated_at`` PAST the
    token's creation time (verified empirically). ``staged_at`` is stamped after that
    write, so it does not have that problem. Non-template ZIPs (slash_commands.zip)
    are never stale.

    Legacy tolerance: tokens minted before the ce_0081 migration carry
    ``staged_at IS NULL`` (additive column, no backfill). Those fall back to the
    BE-9208 export-watermark comparison rather than erroring or being blanket-refused.
    Tokens expire after 15 minutes, so that path self-drains almost immediately.
    """
    if filename not in _TEMPLATE_BEARING_ZIPS:
        return False

    content_stmt = select(func.max(func.coalesce(AgentTemplate.updated_at, AgentTemplate.created_at))).where(
        AgentTemplate.tenant_key == tenant_key
    )
    # tenant_key is redundant for lookup (token is globally unique) but kept in the
    # WHERE so the fail-closed tenant guard sees a properly scoped query rather than a
    # bare token read — same reason increment_download_count takes tenant_key.
    staged_stmt = select(DownloadToken.staged_at).where(
        DownloadToken.token == token, DownloadToken.tenant_key == tenant_key
    )
    export_stmt = select(func.max(AgentTemplate.last_exported_at)).where(AgentTemplate.tenant_key == tenant_key)

    # The public download path carries no ambient tenant; scope with the one resolved
    # from the token row so the fail-closed guard is satisfied (mirrors
    # TokenManager.increment_download_count).
    with tenant_session_context(session, tenant_key):
        content_watermark = (await session.execute(content_stmt)).scalar_one_or_none()
        staged_at = (await session.execute(staged_stmt)).scalar_one_or_none()
        export_watermark = None if staged_at is not None else (await session.execute(export_stmt)).scalar_one_or_none()

    if content_watermark is None:
        # No templates exist at all -> no staged snapshot that can be stale.
        return False

    if staged_at is not None:
        return content_watermark > staged_at

    # Legacy (pre-ce_0081) token: fall back to the tenant-global export watermark.
    if export_watermark is None:
        # Templates exist but NONE was ever exported: the staged ZIP predates all of
        # the tenant's current templates (e.g. staged slash-commands-only when the
        # tenant had no active templates, then templates were added) -> it can only be
        # a pre-change snapshot, so refuse it.
        return True
    return content_watermark > export_watermark


def _toml_string(value: object) -> str:
    """Render a TOML basic string using JSON-compatible escaping."""
    return json_dumps("" if value is None else str(value))


def _codex_agents_to_toml(agents: list[dict]) -> list[tuple[str, str]]:
    """Convert Codex agent dicts to (zip_path, toml_content) pairs.

    Renders each agent as a standalone TOML file that Codex CLI reads from
    ~/.codex/agents/. Uses the gil- prefix to avoid shadowing Codex built-in
    roles. Model and reasoning fields are omitted so agents inherit the parent
    Codex session defaults unless the user explicitly adds overrides.
    """
    entries = []
    for agent in agents:
        # BE-9385b: the assembler supplies ``export_stem`` -- the agent's name
        # already qualified by the product slug. Falling back to agent_name keeps
        # the anonymous system-default bundle, which has no export context, on its
        # old naming.
        stem = agent.get("export_stem") or agent["agent_name"]
        slug = stem.lower().replace(" ", "-").replace("_", "-")
        if not slug.startswith("gil-"):
            slug = f"gil-{slug}"

        instructions = agent.get("developer_instructions", "")

        # The ownership marker leads the file as a TOML comment. Deliberately NOT
        # folded into developer_instructions: that text is the agent's operating
        # identity, and installer bookkeeping does not belong in a persona.
        marker = agent.get("giljo_marker")
        header = f"# {marker}\n" if marker else ""

        toml_content = (
            f"{header}"
            f"name = {_toml_string(slug)}\n"
            f"description = {_toml_string(agent.get('description', ''))}\n"
            f"nickname_candidates = [{_toml_string(slug)}]\n"
            f"developer_instructions = {_toml_string(instructions)}\n"
        )
        entries.append((f"agents/{slug}.toml", toml_content))
    return entries


def _antigravity_plugin_entries(
    export_data: dict,
    slash_templates: dict[str, str],
) -> list[tuple[str, str]]:
    """Build the nested ``plugins/<name>/`` tree for Antigravity CLI (`agy`).

    Produces (zip_path, content) pairs for a single installable plugin bundle
    (spike C3, SOW §4 P2.1):

        plugins/<name>/plugin.json
        plugins/<name>/agents/<agent_dir>/agent.json   (nested config.customAgent)
        plugins/<name>/skills/<skill_path>             (SKILL.md / reference.md)

    `agy plugin install <plugin_dir>` registers the whole tree; agents load ONLY
    from an installed plugin, never from loose files.
    """
    plugin_name = export_data["plugin_name"]
    root = f"plugins/{plugin_name}"

    entries: list[tuple[str, str]] = [
        (f"{root}/plugin.json", json_dumps(export_data["plugin_manifest"], indent=2)),
    ]

    for agent in export_data["agents"]:
        agent_dir = agent["agent_dir"]
        entries.append(
            (
                f"{root}/agents/{agent_dir}/agent.json",
                json_dumps(agent["agent_json"], indent=2),
            )
        )

    for skill_path, content in slash_templates.items():
        entries.append((f"{root}/skills/{skill_path}", content))

    return entries


class FileStaging:
    """
    Manages temporary file staging for download tokens.

    Creates staging directories, generates ZIP files, and handles cleanup
    with multi-tenant isolation and directory traversal protection.
    """

    def __init__(self, base_path: Path | None = None, db_session: AsyncSession | None = None):
        """
        Initialize FileStaging.

        Args:
            base_path: Base directory for staging (defaults to ./temp)
            db_session: Optional AsyncSession for agent template queries
        """
        self.base_path = base_path or Path.cwd() / "temp"
        self.db_session = db_session

    async def create_staging_directory(self, tenant_key: str, token: str) -> Path:
        """
        Create staging directory for a token.

        Creates directory structure: temp/{tenant_key}/{token}/
        with protection against directory traversal attacks.

        Args:
            tenant_key: Tenant identifier
            token: UUID token string

        Returns:
            Path: Staging directory path

        Raises:
            ValueError: If tenant_key or token contain path traversal attempts
        """
        # Prevent directory traversal attacks
        if ".." in tenant_key or "/" in tenant_key or "\\" in tenant_key:
            logger.error(f"Directory traversal attempt detected in tenant_key: {tenant_key}")
            raise ValueError("Invalid tenant_key: path traversal detected")

        if ".." in token or "/" in token or "\\" in token:
            logger.error(f"Directory traversal attempt detected in token: {token}")
            raise ValueError("Invalid token: path traversal detected")

        # Create staging directory
        staging_dir = self.base_path / tenant_key / token
        staging_dir.mkdir(parents=True, exist_ok=True)

        logger.debug(f"Created staging directory: {staging_dir}")
        return staging_dir

    async def stage_slash_commands(
        self,
        staging_path: Path,
        platform: str = "claude_code",
    ) -> tuple[Path | None, str]:
        """
        Stage slash commands as a ZIP file.

        Creates a ZIP file containing platform-specific slash command/skill files.

        Args:
            staging_path: Pre-created staging directory (temp/{tenant_key}/{token}/)
            platform: Target CLI platform (claude_code, gemini_cli, codex_cli)

        Returns:
            Tuple (zip_path|None, message)

        Raises:
            None - returns (None, message) on error
        """
        try:
            staging_path.mkdir(parents=True, exist_ok=True)
            zip_path = staging_path / "slash_commands.zip"

            # Get platform-specific templates (0836b)
            templates = get_all_templates(platform=platform)

            # Create ZIP file with single command
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for filename, content in templates.items():
                    zf.writestr(filename, content)

            logger.info(f"Staged slash commands ZIP: {zip_path} ({len(templates)} files)")
            return (zip_path, f"Successfully staged {len(templates)} slash commands")
        except (OSError, ValueError, RuntimeError) as e:
            if isinstance(e, OSError):
                msg = f"Disk error creating slash commands ZIP: {e}"
            else:
                msg = f"Unexpected error creating slash commands ZIP: {e}"
            logger.exception(msg)
            return (None, msg)

    async def stage_agent_templates(
        self,
        staging_path: Path,
        tenant_key: str,
        db_session: AsyncSession | None = None,
        platform: str = "claude_code",
    ) -> tuple[Path | None, str]:
        """
        Stage agent templates as a ZIP file.

        Queries the database for active agent templates belonging to the
        tenant and creates a ZIP file with platform-appropriate content.

        **Handover 0421**: Updates last_exported_at timestamp for all exported templates
        to enable staleness detection in get_available_agents().
        **Handover 0836a**: Platform-aware rendering via AgentTemplateAssembler.

        Args:
            staging_path: Pre-created staging directory (temp/{tenant_key}/{token}/)
            tenant_key: Tenant identifier
            db_session: Optional DB session override
            platform: Target platform (claude_code, codex_cli, gemini_cli)

        Returns:
            Tuple (zip_path|None, message)

        Raises:
            None - returns (None, message) on error
        """
        session = db_session or self.db_session
        if not session:
            return (None, "Database session not configured for template staging")

        try:
            from datetime import datetime

            staging_path.mkdir(parents=True, exist_ok=True)
            zip_path = staging_path / "agent_templates.zip"

            # Query active templates for tenant
            # BE-9325: soft-delete leaves is_active alone -- deleted_at IS NULL
            # is required or a trashed template ships back onto the user's disk.
            stmt = select(AgentTemplate).where(
                AgentTemplate.tenant_key == tenant_key,
                AgentTemplate.is_active,
                AgentTemplate.deleted_at.is_(None),
            )

            result = await session.execute(stmt)
            all_active = result.scalars().all()

            if not all_active:
                msg = f"No active templates found for tenant: {tenant_key}"
                logger.warning(msg)
                return (None, msg)

            # Apply packaging selection (cap lives in select_templates_for_packaging)
            from .repositories.product_agent_selection import (
                active_product_template_ids,
                build_export_context,
                filter_templates_by_ids,
                record_product_export,
            )
            from .template_renderer import select_templates_for_packaging
            from .tools.agent_template_assembler import AgentTemplateAssembler

            # BE-9385a: the exported set follows the ACTIVE PRODUCT's junction.
            all_active = filter_templates_by_ids(all_active, await active_product_template_ids(session, tenant_key))

            if not all_active:
                msg = "No agents are enabled for the active product"
                logger.warning("%s (tenant: %s)", msg, tenant_key)
                return (None, msg)

            selected = select_templates_for_packaging(all_active)

            # Assemble templates for the target platform (Handover 0836a)
            export_context = await build_export_context(session, tenant_key)
            assembler = AgentTemplateAssembler()
            export_data = assembler.assemble(selected, platform, export_context=export_context)

            # Create ZIP file with platform-appropriate content
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                if platform == EXPORT_CODEX_CLI:
                    for zip_name, content in _codex_agents_to_toml(export_data["agents"]):
                        zf.writestr(zip_name, content)
                elif platform == EXPORT_ANTIGRAVITY_CLI:
                    # Nested plugin tree (manifest + agents/<dir>/agent.json); skills
                    # arrive via the combined giljo_setup ZIP, not this agents-only one.
                    for zip_name, content in _antigravity_plugin_entries(export_data, {}):
                        zf.writestr(zip_name, content)
                else:
                    for agent in export_data["agents"]:
                        zf.writestr(agent["filename"], agent["content"])

            # ═══════════════════════════════════════════════════════════════════════
            # Handover 0421: Update export timestamp for staleness detection
            # ═══════════════════════════════════════════════════════════════════════
            export_timestamp = datetime.now(UTC)

            for template in selected:
                template.last_exported_at = export_timestamp

            # BE-9385e: record it for the product that exported, so this staging
            # does not read as a fresh export in every other product.
            await record_product_export(
                session,
                export_context.product_id if export_context else None,
                tenant_key,
                [t.id for t in selected],
                export_timestamp,
            )

            await session.commit()

            logger.info(f"Updated last_exported_at for {len(selected)} templates at {export_timestamp.isoformat()}")
            # ═══════════════════════════════════════════════════════════════════════

            logger.info(
                f"Staged agent templates ZIP: {zip_path} ({len(selected)} files from {len(all_active)} active templates)"
            )
            return (zip_path, f"Successfully staged {len(selected)} agent templates")
        except (OSError, ValueError, RuntimeError) as e:
            if isinstance(e, OSError):
                msg = f"Disk error staging agent templates: {e}"
            else:
                msg = f"Unexpected error staging agent templates: {e}"
            logger.exception(msg)
            # Rollback on error
            if session:
                await session.rollback()
            return (None, msg)

    async def stage_combined_setup(
        self,
        staging_path: Path,
        tenant_key: str,
        db_session: AsyncSession | None = None,
        platform: str = "claude_code",
        product_id: str | None = None,
    ) -> tuple[Path | None, str]:
        """
        Stage slash commands AND agent templates in a single ZIP (Handover 0907).

        Creates a combined ZIP structured so it extracts directly into the
        platform's home directory root (~/.claude/, ~/.gemini/, ~/.codex/).
        Agent templates are binary content — no LLM processing on the client.

        Args:
            staging_path: Pre-created staging directory
            tenant_key: Tenant identifier
            db_session: Optional DB session override
            platform: Target CLI platform (claude_code, gemini_cli, codex_cli)
            product_id: BE-9557: the caller's already-resolved product binding
                (``bootstrap_setup``'s ``_resolve_product_binding``). ``None``
                resolves the tenant's DEFAULT product instead (see
                ``product_agent_selection._resolve_default_product_id``) --
                this used to be silently dropped even when the caller HAD a
                bound product, so the export followed an arbitrary shown
                product instead of the one the caller asked for.

        Returns:
            Tuple (zip_path|None, message)
        """
        from .tools.slash_command_templates import _VALID_PLATFORMS, get_all_templates

        if platform not in _VALID_PLATFORMS:
            raise ValueError(f"Unknown platform '{platform}'. Must be one of: {', '.join(_VALID_PLATFORMS)}")

        session = db_session or self.db_session

        try:
            staging_path.mkdir(parents=True, exist_ok=True)
            zip_path = staging_path / "giljo_setup.zip"

            # --- Slash commands ---
            slash_templates = get_all_templates(platform=platform)

            # Map slash command filenames into platform directory structure.
            # BE-6117: the skill-install platform set is owned by the registry.
            slash_dir = "skills" if platform in SKILL_SLASH_PLATFORMS else "commands"

            # --- Agent templates (if DB session available) ---
            agent_entries: list[tuple[str, str]] = []
            selected_templates: list = []
            export_data: dict | None = None
            export_context = None  # BE-9385e: read by the export-timestamp write below.

            if session:
                from datetime import datetime

                from .repositories.product_agent_selection import (
                    active_product_template_ids,
                    build_export_context,
                    filter_templates_by_ids,
                    record_product_export,
                    template_ids_for_product,
                )
                from .template_renderer import select_templates_for_packaging
                from .tools.agent_template_assembler import AgentTemplateAssembler

                # BE-9325: soft-delete leaves is_active alone -- deleted_at IS NULL
                # is required or a trashed template ships back onto the user's disk.
                result = await session.execute(
                    select(AgentTemplate).where(
                        AgentTemplate.tenant_key == tenant_key,
                        AgentTemplate.is_active,
                        AgentTemplate.deleted_at.is_(None),
                    )
                )
                # BE-9385a/BE-9557: the exported set follows the REQUESTED product's
                # junction when the caller resolved one, else the DEFAULT product's.
                # An empty result here is not an error on this path -- the combined
                # ZIP still ships the slash commands, exactly as it already does for
                # a tenant with no active templates at all.
                if product_id:
                    ids = await template_ids_for_product(session, product_id, tenant_key)
                else:
                    ids = await active_product_template_ids(session, tenant_key)
                all_active = filter_templates_by_ids(result.scalars().all(), ids)

                if all_active:
                    selected_templates = select_templates_for_packaging(all_active)
                    export_context = await build_export_context(session, tenant_key, product_id=product_id)
                    assembler = AgentTemplateAssembler()
                    export_data = assembler.assemble(selected_templates, platform, export_context=export_context)

                    if platform == EXPORT_CODEX_CLI:
                        agent_entries = _codex_agents_to_toml(export_data["agents"])
                    elif platform != EXPORT_ANTIGRAVITY_CLI:
                        for agent in export_data["agents"]:
                            agent_entries.append(
                                (
                                    f"agents/{agent['filename']}",
                                    agent["content"],
                                )
                            )

            # --- Build ZIP ---
            if platform == EXPORT_ANTIGRAVITY_CLI:
                # Single nested plugin bundle: plugin.json + agents/ + skills/
                # under plugins/<name>/. If no active templates, still emit a
                # valid plugin (manifest + skills) so `agy plugin install` works.
                if export_data is None:
                    from .tools.agent_template_assembler import AgentTemplateAssembler

                    export_data = AgentTemplateAssembler().assemble([], platform)
                plugin_entries = _antigravity_plugin_entries(export_data, slash_templates)
                agent_entries = [e for e in plugin_entries if "/agents/" in e[0]]
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for zip_name, content in plugin_entries:
                        zf.writestr(zip_name, content)
            else:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for filename, content in slash_templates.items():
                        zf.writestr(f"{slash_dir}/{filename}", content)
                    for zip_name, content in agent_entries:
                        zf.writestr(zip_name, content)

            # Update export timestamps
            if selected_templates and session:
                export_timestamp = datetime.now(UTC)
                for t in selected_templates:
                    t.last_exported_at = export_timestamp
                # BE-9385e: and against the product that exported them.
                await record_product_export(
                    session,
                    export_context.product_id if export_context else None,
                    tenant_key,
                    [t.id for t in selected_templates],
                    export_timestamp,
                )
                await session.commit()

            total = len(slash_templates) + len(agent_entries)
            logger.info(f"Staged combined setup ZIP: {zip_path} ({total} files for {platform})")
            return (
                zip_path,
                f"Successfully staged {total} files ({len(slash_templates)} commands, {len(agent_entries)} agents)",
            )

        except (OSError, ValueError, RuntimeError) as e:
            msg = f"Error staging combined setup ZIP: {e}"
            logger.exception(msg)
            if session:
                await session.rollback()
            if isinstance(e, ValueError):
                raise
            return (None, msg)

    async def cleanup(self, tenant_key: str, token: str) -> bool:
        """
        Remove staging directory and all contents.

        Performs best-effort cleanup after download completes.
        Does not raise exceptions if directory doesn't exist.

        Args:
            tenant_key: Tenant identifier
            token: UUID token string

        Returns:
            bool: True if cleanup succeeded, False otherwise
        """
        try:
            staging_dir = self.base_path / tenant_key / token

            if not staging_dir.exists():
                logger.debug(f"Staging directory already removed: {staging_dir}")
                return True

            # Remove directory and all contents
            shutil.rmtree(staging_dir)

            logger.debug(f"Cleaned up staging directory: {staging_dir}")
            return True

        except (OSError, RuntimeError) as e:
            # Best-effort cleanup - log but don't raise
            logger.warning(f"Error cleaning up staging directory: {e}")
            return False

    async def purge_token_dir(self, tenant_key: str, token: str) -> bool:
        """Path-validated reap of a single expired token's staging directory.

        Used by the download-token reaper (BE-3011): when an expired token row
        is deleted, its on-disk staging dir (``temp/{tenant_key}/{token}/``) must
        be removed too, or the dirs orphan and slowly fill the disk (a CE
        self-hoster has no operator to clean them).

        SECURITY CONTRACT — this runs over tenant/token values and must NEVER
        delete outside the staging root:
        1. Reuse the ``create_staging_directory`` traversal guard (reject ``..``
           ``/`` ``\\`` in either component).
        2. Resolve the real absolute path (following any symlink) and ASSERT it
           is STRICTLY inside the resolved staging root — the resolved path must
           not be the root itself and the root must be one of its parents. Any
           path that escapes the root (``..`` segments, an absolute seed, or a
           symlink pointing outside) is refused.
        3. Never ``rmtree`` the staging root or a tenant root wholesale.

        Any refusal or error is logged and returns ``False`` — it NEVER raises
        into the reaper loop. A missing directory is a safe no-op returning
        ``True`` (idempotent: the CE installer reruns the reaper every boot).

        Returns:
            bool: True if the dir was removed or already absent; False if the
            input was refused or removal failed.
        """
        # (1) Cheap traversal-character guard (mirrors create_staging_directory).
        if not tenant_key or ".." in tenant_key or "/" in tenant_key or "\\" in tenant_key:
            logger.error("Refusing staging-dir purge: invalid tenant_key (path traversal)")
            return False
        if not token or ".." in token or "/" in token or "\\" in token:
            logger.error("Refusing staging-dir purge: invalid token (path traversal)")
            return False

        try:
            root = self.base_path.resolve()
            staging_dir = self.base_path / tenant_key / token
            resolved = staging_dir.resolve()

            # (2) Containment assertion — the load-bearing security gate. The
            # resolved path must be a STRICT descendant of the resolved root.
            # This refuses absolute seeds, ``..`` escapes, and symlinks whose
            # real target lies outside the staging root.
            if resolved == root or root not in resolved.parents:
                logger.error("Refusing staging-dir purge: resolved path escapes staging root")
                return False

            # (3) Idempotent: nothing to do if it is already gone.
            if not staging_dir.exists():
                logger.debug("Staging dir already absent (no-op): %s", staging_dir)
                return True

            shutil.rmtree(resolved)
            logger.debug("Reaped expired staging dir: %s", resolved)
            return True

        except (OSError, RuntimeError) as exc:
            # Best-effort reap: log but never raise into the reaper loop.
            logger.warning("Error reaping staging dir: %s", exc)
            return False

    @staticmethod
    def validate_filename(filename: str) -> bool:
        """Validate filename to prevent directory traversal and invalid characters."""
        if ".." in filename or "/" in filename or "\\" in filename:
            return False
        return re.match(r"^[a-zA-Z0-9._-]+$", filename) is not None
