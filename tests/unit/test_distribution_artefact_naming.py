# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from pathlib import Path

from giljo_mcp import branding


REPO_ROOT = Path(__file__).resolve().parents[2]


def _slugs_before_version_var(text: str, version_pattern: str) -> set[str]:
    pattern = rf"([A-Za-z0-9_.-]+?)-{version_pattern}\.tar\.gz"
    return {m.group(1) for m in re.finditer(pattern, text)}


class TestDistributionArtefactSlugMatchesSingleSourceOfTruth:

    def test_install_ps1_uses_dist_slug(self):
        text = (REPO_ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
        slugs = _slugs_before_version_var(text, re.escape("$version"))
        assert slugs, "install.ps1: no versioned tarball name found (did the pattern change?)"
        assert slugs == {branding.DIST_SLUG}, (
            f"install.ps1 tarball name uses {sorted(slugs)}, expected {{'{branding.DIST_SLUG}'}}"
        )

    def test_install_sh_uses_dist_slug(self):
        text = (REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
        slugs = _slugs_before_version_var(text, re.escape("${RELEASE_VERSION}"))
        assert slugs, "install.sh: no versioned tarball name found (did the pattern change?)"
        assert slugs == {branding.DIST_SLUG}, (
            f"install.sh tarball name uses {sorted(slugs)}, expected {{'{branding.DIST_SLUG}'}}"
        )

    def test_release_workflow_yml_uses_dist_slug(self):
        text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        slugs = _slugs_before_version_var(text, re.escape("${VERSION}"))
        assert slugs, "release.yml: no versioned tarball name found (did the pattern change?)"
        assert slugs == {branding.DIST_SLUG}, (
            f"release.yml tarball name uses {sorted(slugs)}, expected {{'{branding.DIST_SLUG}'}}"
        )

    def test_dist_slug_is_derived_not_hand_copied(self):
        assert branding.MCP_ALIAS.replace("_", "-") == branding.DIST_SLUG
