# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import zipfile

import pytest

from giljo_mcp.file_staging import FileStaging


@pytest.fixture
def staging_dir(tmp_path):
    d = tmp_path / "staging"
    d.mkdir()
    return d


class TestStageSetupBundle:

    @pytest.mark.asyncio
    async def test_claude_code_zip_structure(self, staging_dir):
        staging = FileStaging()

        zip_path, msg = await staging.stage_setup_bundle(staging_dir, platform="claude_code")

        assert zip_path is not None
        assert zip_path.exists()
        assert "Successfully staged" in msg

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "commands/giljo.md" in names
            assert [n for n in names if n.startswith("agents/")] == []

    @pytest.mark.asyncio
    async def test_codex_cli_zip_structure(self, staging_dir):
        staging = FileStaging()

        zip_path, _ = await staging.stage_setup_bundle(staging_dir, platform="codex_cli")

        assert zip_path is not None

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "skills/giljo/SKILL.md" in names
            assert [n for n in names if n.startswith("agents/")] == []

    @pytest.mark.asyncio
    async def test_generic_zip_structure(self, staging_dir):
        staging = FileStaging()

        zip_path, _ = await staging.stage_setup_bundle(staging_dir, platform="generic")

        assert zip_path is not None

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert [n for n in names if n.startswith("commands/")] == ["commands/giljo_reference.md"]
            assert [n for n in names if n.startswith("agents/")] == []

    @pytest.mark.asyncio
    async def test_zip_filename(self, staging_dir):
        staging = FileStaging()

        zip_path, _ = await staging.stage_setup_bundle(staging_dir, platform="claude_code")

        assert zip_path.name == "giljo_setup.zip"

    @pytest.mark.asyncio
    async def test_invalid_platform_raises(self, staging_dir):
        staging = FileStaging()

        with pytest.raises(ValueError, match="Unknown platform"):
            await staging.stage_setup_bundle(staging_dir, platform="invalid")
