# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Guard against the distribution-tarball name drifting from branding.DIST_SLUG
again (INF-9483-follow / BE-9275 close-out).

The "GiljoAI MCP" -> "Giljo HQ" rename (BE-9275) renamed the release tarball
in .github/workflows/release.yml and left every OTHER producer/consumer of
that name alone, so v2.0.3 shipped publicly as ``giljoai-mcp-2.0.3.tar.gz``.
``tests/unit/test_release_workflow.py`` only ever checked release.yml's own
internal self-consistency -- that narrowness is exactly why the drift wasn't
caught. This file is the sibling that closes the gap for every producer or
consumer that SHIPS to CE: ``scripts/install.ps1``, ``scripts/install.sh``,
and ``.github/workflows/release.yml`` (``CE_SHIPPED_WORKFLOWS=(release.yml)``
in export_ce.sh). Each is checked against a single source of truth
(``branding.DIST_SLUG``), so a future rename that changes one constant and
misses a site fails here instead of shipping.

``scripts/export_ce_lan.sh`` is private tooling stripped from the CE export
(it is not in the four preserved scripts/ files) -- its equivalent assertion
lives in ``tests/scripts/test_distribution_artefact_naming_private.py``,
which is stripped alongside it (.export-exclude pairs tests/scripts/ with
the other private-only tooling it tests, INF-9311's precedent). Do not
re-add an export_ce_lan.sh check here: it does not exist in a shipped tree
and a skip/exists-guard would silence exactly the drift this suite exists
to catch (TSK-9317).

Deliberately NOT scoped to the string "giljoai-mcp" anywhere in these files --
that would false-positive on legitimate old-name uses that must stay green:
the systemd unit ``giljoai-mcp.service``, the default install directories
(``~/giljoai-mcp``), the LAN repo path ``giljoai/GiljoAI_MCP``, the desktop
file ``giljoai-mcp.desktop``, the release branch ``release-giljoai-mcp``, and
arbitrary test fixture strings in test_version_service.py. Each regex below
anchors on the specific "<slug>-<version-var>.tar.gz" artefact-name shape, not
on the bare substring.
"""

from __future__ import annotations

import re
from pathlib import Path

from giljo_mcp import branding


REPO_ROOT = Path(__file__).resolve().parents[2]


def _slugs_before_version_var(text: str, version_pattern: str) -> set[str]:
    r"""Extract the slug immediately preceding a versioned ``.tar.gz`` name.

    ``version_pattern`` is the exact (already-escaped) regex for the
    version placeholder used at that site, e.g. ``\$version`` or
    ``\$\{DIST_VER\}``.
    """
    pattern = rf"([A-Za-z0-9_.-]+?)-{version_pattern}\.tar\.gz"
    return {m.group(1) for m in re.finditer(pattern, text)}


class TestDistributionArtefactSlugMatchesSingleSourceOfTruth:
    """Every CE-shipped producer/consumer of the release tarball name must
    agree with branding.DIST_SLUG -- not just agree with each other."""

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
        """release.yml (public-facing GitHub release) must also match the
        same single source of truth, not just be internally self-consistent
        (that half is covered by test_release_workflow.py)."""
        text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        slugs = _slugs_before_version_var(text, re.escape("${VERSION}"))
        assert slugs, "release.yml: no versioned tarball name found (did the pattern change?)"
        assert slugs == {branding.DIST_SLUG}, (
            f"release.yml tarball name uses {sorted(slugs)}, expected {{'{branding.DIST_SLUG}'}}"
        )

    def test_dist_slug_is_derived_not_hand_copied(self):
        """branding.DIST_SLUG must be a transform of MCP_ALIAS, not a second
        hardcoded literal -- otherwise this whole guard is one rename away
        from drifting itself."""
        assert branding.MCP_ALIAS.replace("_", "-") == branding.DIST_SLUG
