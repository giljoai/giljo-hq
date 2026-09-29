# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
import re
import shutil
import zipfile
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from .platform_registry import SKILL_SLASH_PLATFORMS
from .tools.slash_command_templates import get_all_templates
from .utils.log_sanitizer import mask_token


logger = logging.getLogger(__name__)


class FileStaging:

    def __init__(self, base_path: Path | None = None, db_session: AsyncSession | None = None):
        self.base_path = base_path or Path.cwd() / "temp"
        self.db_session = db_session

    async def create_staging_directory(self, tenant_key: str, token: str) -> Path:
        if ".." in tenant_key or "/" in tenant_key or "\\" in tenant_key:
            logger.error(f"Directory traversal attempt detected in tenant_key: {tenant_key}")
            raise ValueError("Invalid tenant_key: path traversal detected")

        if ".." in token or "/" in token or "\\" in token:
            logger.error(f"Directory traversal attempt detected in token: {mask_token(token)}")
            raise ValueError("Invalid token: path traversal detected")

        staging_dir = self.base_path / tenant_key / token
        staging_dir.mkdir(parents=True, exist_ok=True)

        logger.debug("Created staging directory: %s/%s", self.base_path / tenant_key, mask_token(token))
        return staging_dir

    async def stage_slash_commands(
        self,
        staging_path: Path,
        platform: str = "claude_code",
    ) -> tuple[Path | None, str]:
        try:
            staging_path.mkdir(parents=True, exist_ok=True)
            zip_path = staging_path / "slash_commands.zip"

            templates = get_all_templates(platform=platform)

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

    async def stage_setup_bundle(
        self,
        staging_path: Path,
        platform: str = "claude_code",
    ) -> tuple[Path | None, str]:
        from .tools.slash_command_templates import _VALID_PLATFORMS, get_all_templates

        if platform not in _VALID_PLATFORMS:
            raise ValueError(f"Unknown platform '{platform}'. Must be one of: {', '.join(_VALID_PLATFORMS)}")

        try:
            staging_path.mkdir(parents=True, exist_ok=True)
            zip_path = staging_path / "giljo_setup.zip"

            slash_templates = get_all_templates(platform=platform)
            slash_dir = "skills" if platform in SKILL_SLASH_PLATFORMS else "commands"

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for filename, content in slash_templates.items():
                    zf.writestr(f"{slash_dir}/{filename}", content)

            logger.info(f"Staged setup bundle ZIP: {zip_path} ({len(slash_templates)} files for {platform})")
            return (zip_path, f"Successfully staged {len(slash_templates)} skill/command files")

        except (OSError, ValueError, RuntimeError) as e:
            msg = f"Error staging setup bundle ZIP: {e}"
            logger.exception(msg)
            if isinstance(e, ValueError):
                raise
            return (None, msg)

    async def cleanup(self, tenant_key: str, token: str) -> bool:
        try:
            staging_dir = self.base_path / tenant_key / token

            if not staging_dir.exists():
                logger.debug(f"Staging directory already removed: {staging_dir}")
                return True

            shutil.rmtree(staging_dir)

            logger.debug(f"Cleaned up staging directory: {staging_dir}")
            return True

        except (OSError, RuntimeError) as e:
            logger.warning(f"Error cleaning up staging directory: {e}")
            return False

    async def purge_token_dir(self, tenant_key: str, token: str) -> bool:
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

            if resolved == root or root not in resolved.parents:
                logger.error("Refusing staging-dir purge: resolved path escapes staging root")
                return False

            if not staging_dir.exists():
                logger.debug("Staging dir already absent (no-op): %s", staging_dir)
                return True

            shutil.rmtree(resolved)
            logger.debug("Reaped expired staging dir: %s", resolved)
            return True

        except (OSError, RuntimeError) as exc:
            logger.warning("Error reaping staging dir: %s", exc)
            return False

    @staticmethod
    def validate_filename(filename: str) -> bool:
        if ".." in filename or "/" in filename or "\\" in filename:
            return False
        return re.match(r"^[a-zA-Z0-9._-]+$", filename) is not None
