# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "release.yml"


class TestReleaseWorkflowStructure:

    def setup_method(self):
        assert RELEASE_YML.exists(), f"release.yml not found at {RELEASE_YML}"
        with open(RELEASE_YML) as f:
            self.workflow = yaml.safe_load(f)

    def test_trigger_is_tag_push(self):
        trigger = self.workflow.get("on") or self.workflow.get(True)
        assert trigger is not None, "No 'on' trigger found in workflow"
        assert "push" in trigger
        tags = trigger["push"]["tags"]
        assert any("v*" in t for t in tags), f"No v* tag pattern found: {tags}"

    def test_permissions_contents_write(self):
        assert self.workflow["permissions"]["contents"] == "write"

    def test_release_job_exists(self):
        assert "release" in self.workflow["jobs"]

    def test_runs_on_ubuntu(self):
        job = self.workflow["jobs"]["release"]
        assert job["runs-on"] == "ubuntu-latest"

    def test_checkout_step_exists(self):
        steps = self.workflow["jobs"]["release"]["steps"]
        checkout_steps = [s for s in steps if s.get("uses", "").startswith("actions/checkout")]
        assert len(checkout_steps) >= 1, "No checkout step found"

    def test_version_extraction_step(self):
        steps = self.workflow["jobs"]["release"]["steps"]
        version_steps = [s for s in steps if s.get("id") == "version"]
        assert len(version_steps) == 1, "Expected exactly one 'version' step"
        run_script = version_steps[0].get("run", "")
        assert "GITHUB_REF_NAME" in run_script, "Version step must reference GITHUB_REF_NAME"

    def test_strip_dev_files_step(self):
        steps = self.workflow["jobs"]["release"]["steps"]
        strip_steps = [s for s in steps if "strip" in s.get("name", "").lower() or "dev" in s.get("name", "").lower()]
        assert len(strip_steps) >= 1, "No dev file stripping step found"

    def test_tarball_creation_step(self):
        steps = self.workflow["jobs"]["release"]["steps"]
        tarball_steps = [s for s in steps if s.get("id") == "tarball"]
        assert len(tarball_steps) == 1, "Expected exactly one 'tarball' step"
        run_script = tarball_steps[0].get("run", "")
        assert "tar" in run_script, "Tarball step must use tar command"
        assert "giljo-hq-" in run_script, "Tarball must use the giljo-hq product naming"

    def test_every_asset_name_site_uses_the_same_slug(self):
        steps = self.workflow["jobs"]["release"]["steps"]
        by_id = {s.get("id"): s.get("run", "") for s in steps if s.get("id")}

        slugs = set()
        for step_id in ("tarball", "checksum", "manifest"):
            script = by_id.get(step_id, "")
            assert script, f"Expected a '{step_id}' step with a run script"
            for match in re.finditer(r"([A-Za-z0-9_.-]+?)-\$\{VERSION\}\.(?:tar\.gz|sha256)", script):
                slugs.add(match.group(1))

        assert slugs, "No versioned asset names found in the tarball/checksum/manifest steps"
        assert len(slugs) == 1, (
            f"Asset-name sites disagree: {sorted(slugs)}. All four must use one slug, "
            "or version-manifest.json points at an asset that was never published."
        )

    def test_checksum_step(self):
        steps = self.workflow["jobs"]["release"]["steps"]
        checksum_steps = [s for s in steps if s.get("id") == "checksum"]
        assert len(checksum_steps) == 1, "Expected exactly one 'checksum' step"
        run_script = checksum_steps[0].get("run", "")
        assert "sha256sum" in run_script, "Checksum step must use sha256sum"

    def test_version_manifest_step(self):
        steps = self.workflow["jobs"]["release"]["steps"]
        manifest_steps = [s for s in steps if s.get("id") == "manifest"]
        assert len(manifest_steps) == 1, "Expected exactly one 'manifest' step"
        run_script = manifest_steps[0].get("run", "")
        assert "version-manifest.json" in run_script

    def test_version_manifest_contains_required_fields(self):
        steps = self.workflow["jobs"]["release"]["steps"]
        manifest_step = next(s for s in steps if s.get("id") == "manifest")
        run_script = manifest_step.get("run", "")
        for field in ("version", "tarball_url", "sha256", "min_python", "min_postgres"):
            assert field in run_script, f"Manifest template missing field: {field}"

    def test_gh_release_step(self):
        steps = self.workflow["jobs"]["release"]["steps"]
        release_steps = [s for s in steps if "softprops/action-gh-release" in s.get("uses", "")]
        assert len(release_steps) == 1, "Expected exactly one gh-release step"

    def test_gh_release_has_three_assets(self):
        steps = self.workflow["jobs"]["release"]["steps"]
        release_step = next(s for s in steps if "softprops/action-gh-release" in s.get("uses", ""))
        files_config = release_step.get("with", {}).get("files", "")
        assert "tarball" in files_config, "Release must include tarball asset"
        assert "checksum" in files_config or "CHECKSUM" in files_config, "Release must include checksum asset"
        assert "manifest" in files_config or "MANIFEST" in files_config, "Release must include manifest asset"

    def test_gh_release_generates_notes(self):
        steps = self.workflow["jobs"]["release"]["steps"]
        release_step = next(s for s in steps if "softprops/action-gh-release" in s.get("uses", ""))
        with_config = release_step.get("with", {})
        assert with_config.get("generate_release_notes") is True

    def test_prerelease_detection(self):
        steps = self.workflow["jobs"]["release"]["steps"]
        version_step = next(s for s in steps if s.get("id") == "version")
        run_script = version_step.get("run", "")
        assert "PRERELEASE" in run_script, "Version step must set PRERELEASE output"

    def test_prerelease_flag_wired_to_release(self):
        steps = self.workflow["jobs"]["release"]["steps"]
        release_step = next(s for s in steps if "softprops/action-gh-release" in s.get("uses", ""))
        with_config = release_step.get("with", {})
        prerelease_value = str(with_config.get("prerelease", ""))
        assert "PRERELEASE" in prerelease_value or "prerelease" in prerelease_value.lower(), (
            "Release step must wire prerelease flag from version step"
        )


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[2] / ".export-exclude").exists(),
    reason=".export-exclude not present (public repo)",
)
class TestExportExcludeAllowsRelease:

    def setup_method(self):
        exclude_file = REPO_ROOT / ".export-exclude"
        with open(exclude_file) as f:
            self.lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

    def test_no_blanket_workflow_exclusion(self):
        assert ".github/workflows/" not in self.lines, ".export-exclude still has blanket .github/workflows/ exclusion"

    def test_ci_yml_excluded(self):
        assert ".github/workflows/ci.yml" in self.lines

    def test_frontend_yml_excluded(self):
        assert ".github/workflows/frontend.yml" in self.lines

    def test_codeql_yml_excluded(self):
        assert ".github/workflows/codeql.yml" in self.lines

    def test_release_yml_not_excluded(self):
        release_exclusions = [
            line
            for line in self.lines
            if ("release" in line.lower() and "workflow" in line.lower()) or line == ".github/workflows/release.yml"
        ]
        assert len(release_exclusions) == 0, f"release.yml is excluded: {release_exclusions}"
