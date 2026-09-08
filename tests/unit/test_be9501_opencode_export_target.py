# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9501: every tool a user can CONNECT must be a tool we can INSTALL for.

THE DEFECT, as the operator hit it: he connected opencode from the setup wizard,
ran ``giljo_setup``, and got manual download steps and no agents. opencode was a
first-class *harness* -- detected, launchable, spawnable -- but not an *export
target*, so the install path fell through to ``generic``. The registry even said
so in a comment: "NOT an export target (no agent-template install path shipped)."

That is one list disagreeing with another, silently. The wizard offers six tools;
the installer knew four. Nothing failed loudly -- the user just got nothing.

THE CLASS, not the instance: the sweep below asserts the two lists agree, so
adding a seventh connectable tool without an install path turns CI red instead of
shipping a dead card.

FORMAT PROVENANCE (why these exact fields): verified empirically against opencode
1.18.22 on 2026-08-25 -- a probe agent carrying exactly ``description`` +
``mode: subagent`` was DISCOVERED and SPAWNED by a live session, returning its
sentinel. Not taken from docs alone: the published command docs claim a
``template`` field is required, while a working command file on the same machine
has no such field. Docs and behaviour disagree here, so behaviour won.
"""

from __future__ import annotations

import pathlib
import re

from giljo_mcp.install_targets import _USER_INSTALL_KEY, INSTALL_PATHS
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.platform_registry import (
    EXPORT_ANTIGRAVITY_CLI,
    EXPORT_CLAUDE_CODE,
    EXPORT_CODEX_CLI,
    EXPORT_GEMINI_CLI,
    EXPORT_GENERIC,
    EXPORT_OPENCODE,
    EXPORT_PLATFORMS,
    HARNESSES,
)
from giljo_mcp.tools.agent_template_assembler import AgentTemplateAssembler
from giljo_mcp.tools.setup_instructions import build_setup_instructions
from giljo_mcp.tools.slash_command_templates import get_all_templates


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SETUP_TOOLS_JS = REPO_ROOT / "frontend" / "src" / "config" / "setupTools.js"


def _template() -> AgentTemplate:
    return AgentTemplate(
        name="reviewer",
        role="reviewer",
        description="Reviews code for correctness, quality and edition boundaries",
        system_instructions="You review code against the Giljo quality bar.",
    )


class TestConnectableImpliesInstallable:
    """The sweep that makes this a class fix rather than a one-off."""

    def _wizard_tool_ids(self) -> set[str]:
        js = SETUP_TOOLS_JS.read_text(encoding="utf-8")
        block = re.search(r"SETUP_TOOLS\s*=\s*\[(.*?)\]", js, re.S)
        assert block, "SETUP_TOOLS not found in setupTools.js"
        return set(re.findall(r"\{ id: '([\w]+)'", block.group(1)))

    def test_every_wizard_tool_has_an_install_path(self) -> None:
        # 'generic' is in both lists by design (the pseudo-platform). Anything the
        # user can pick in the Connect wizard must resolve to somewhere we can put
        # agent files, or picking it produces a connected tool with no crew.
        missing = sorted(self._wizard_tool_ids() - set(INSTALL_PATHS))
        assert not missing, (
            f"tool(s) {missing} are offered in the setup wizard but have no entry in "
            "INSTALL_PATHS -- giljo_setup will fall through to 'generic' and hand the "
            "user manual steps instead of installing agents. This is exactly the "
            "opencode defect (BE-9501)."
        )

    def test_every_export_platform_can_actually_be_assembled(self) -> None:
        # A platform in the enum with no assembler branch would raise at install
        # time rather than at import time -- i.e. only for the user who picks it.
        assembler = AgentTemplateAssembler()
        for platform in EXPORT_PLATFORMS:
            out = assembler.assemble([_template()], platform)
            assert out["agents"], f"{platform} assembled zero agent files"
            assert out["platform"] == platform

    def test_every_export_platform_declares_where_its_user_install_lives(self) -> None:
        missing = sorted(set(INSTALL_PATHS) - set(_USER_INSTALL_KEY))
        assert not missing, f"platform(s) {missing} have install paths but no declared user-level key"
        for platform, key in _USER_INSTALL_KEY.items():
            assert key in INSTALL_PATHS[platform], f"{platform}'s user key '{key}' is not one of its own install paths"

    def test_no_harness_is_left_without_an_export_target(self) -> None:
        # opencode sat at export_platform=None for months while being fully
        # detectable and launchable. If a future harness lands the same way, this
        # names it rather than letting it fall through to 'generic' silently.
        orphans = sorted(h.harness for h in HARNESSES if h.export_platform is None)
        assert not orphans, (
            f"harness(es) {orphans} are detectable/launchable but have no export target, "
            "so giljo_setup cannot install agents for them"
        )


class TestOpencodeFileFormat:
    """The shape a live opencode session accepted, pinned."""

    def _rendered(self) -> dict:
        return AgentTemplateAssembler().assemble([_template()], EXPORT_OPENCODE)["agents"][0]

    def test_filename_is_the_agent_identifier(self) -> None:
        # opencode derives the agent name from the FILENAME, which is why the
        # frontmatter carries no name field.
        assert self._rendered()["filename"] == "reviewer.md"

    def test_frontmatter_carries_description_and_subagent_mode(self) -> None:
        content = self._rendered()["content"]
        assert content.startswith("---\n")
        frontmatter = content.split("---", 2)[1]
        assert "description:" in frontmatter, "opencode does not advertise a skill-less agent to the model"
        assert "mode: subagent" in frontmatter, (
            "Giljo roles are delegated to by the orchestrator, never user-selected; "
            "primary mode would clutter the picker with roles nobody drives directly"
        )

    def test_frontmatter_omits_fields_opencode_does_not_use(self) -> None:
        frontmatter = self._rendered()["content"].split("---", 2)[1]
        # name: the filename is the id. color: no palette mapping exists.
        # model: pinning one fights the user's own provider config (opencode users
        # commonly run local gateways).
        for field in ("name:", "color:", "model:"):
            assert field not in frontmatter, f"opencode frontmatter must not carry {field}"

    def test_install_paths_are_plural_directories(self) -> None:
        # THE trap: opencode never reads the singular 'agent/'. Installing there
        # reports success and does nothing -- the first agent to attempt this
        # install guessed singular and would have shipped dead files.
        paths = INSTALL_PATHS[EXPORT_OPENCODE]
        assert paths["user"] == "~/.config/opencode/agents/"
        assert paths["project"] == ".opencode/agents/"
        for value in paths.values():
            assert "/agents/" in value and "/agent/" not in value

    def test_body_survives_into_the_file(self) -> None:
        content = self._rendered()["content"]
        assert "You review code against the Giljo quality bar." in content


class TestFullHarnessParity:
    """opencode must reach the SAME four surfaces the other CLIs get, not just agents.

    The operator's words: "we need to fix it so it is on parity with claude codex
    gemini and antigravity -- that means agents, skills and agents.md modification
    just like all those other harnesses". Fixing only the agent templates would
    have left a tool that installs a crew but cannot be driven: no /giljo command
    to load the routing guide, and no durable primer so the next session starts
    ignorant again.

    Each assertion below names the surface, so a future platform added with three
    of four wired fails with the missing one named.
    """

    _REAL_CLI_PLATFORMS = (
        EXPORT_CLAUDE_CODE,
        EXPORT_GEMINI_CLI,
        EXPORT_CODEX_CLI,
        EXPORT_ANTIGRAVITY_CLI,
        EXPORT_OPENCODE,
    )

    def test_every_real_cli_ships_a_giljo_command_file(self) -> None:
        for platform in self._REAL_CLI_PLATFORMS:
            files = get_all_templates(platform=platform)
            assert files, f"{platform} ships no /giljo command or skill file at all"
            assert any("giljo" in name for name in files), (
                f"{platform}'s command bundle has no giljo entry: {sorted(files)}"
            )

    def test_every_real_cli_gets_its_own_setup_instructions(self) -> None:
        # The generic fallthrough is the "your platform was not identified" text --
        # manual download steps and nothing installed. A real CLI landing there is
        # the opencode defect exactly.
        generic = build_setup_instructions(EXPORT_GENERIC, "https://example/x.zip", None)
        for platform in self._REAL_CLI_PLATFORMS:
            out = build_setup_instructions(platform, "https://example/x.zip", None)
            assert out != generic, (
                f"{platform} falls through to the generic manual-steps text -- it has no "
                "install branch of its own, so giljo_setup installs nothing for it"
            )

    def test_every_real_cli_persists_a_primer_to_its_startup_context(self) -> None:
        # Step P: the durable context file each harness reads on boot. Without it a
        # fresh session has no idea what Giljo HQ is until something loads the guide.
        for platform in self._REAL_CLI_PLATFORMS:
            out = build_setup_instructions(platform, "https://example/x.zip", None)
            assert "Step P" in out, f"{platform}'s instructions never persist the primer"

    def test_opencode_instructions_name_its_three_real_locations(self) -> None:
        out = build_setup_instructions(EXPORT_OPENCODE, "https://example/x.zip", None)
        assert "~/.config/opencode/agents/" in out
        assert "~/.config/opencode/commands/" in out
        assert "AGENTS.md" in out, "opencode reads ~/.config/opencode/AGENTS.md as its global rules file"

    def test_opencode_instructions_warn_about_the_singular_directory_trap(self) -> None:
        # Not decoration: the first agent to attempt this install guessed the
        # singular names, where opencode never looks and an install silently no-ops.
        out = build_setup_instructions(EXPORT_OPENCODE, "https://example/x.zip", None)
        assert "opencode/command/" in out and "PLURAL" in out


class TestTheDoorTheFixDidNotClose:
    """Gaps a read-only audit found AFTER the export-target work looked complete.

    Both are the same failure the whole ticket is about -- one table knowing about
    opencode while another does not -- reached through surfaces the first pass did
    not touch. Kept as their own class because each was found by attacking a claim
    of completeness, not by writing the feature.
    """

    def test_giljo_setup_description_names_every_platform_it_accepts(self) -> None:
        # The signature type-accepts opencode (it is registry-derived), but the
        # human-readable DESCRIPTION is what an LLM reads to choose a value, and it
        # listed only four CLIs with claude_code as the default. An agent running
        # inside opencode would omit the parameter, take the default, and install
        # Claude-format files into ~/.claude/ -- silently, no error. That is the
        # operator's original bug reached through a different door.
        src = (REPO_ROOT / "api" / "endpoints" / "mcp_tools" / "_setup_tools.py").read_text(encoding="utf-8")
        block = src[src.index("description=(") : src.index('annotations=_tool_hints("giljo_setup")')]
        for platform in EXPORT_PLATFORMS:
            if platform == EXPORT_GENERIC:
                continue  # the pseudo-platform is never something a caller declares
            assert platform in block, (
                f"giljo_setup's tool description does not mention '{platform}', so an agent "
                "running in that tool cannot know to pass it and will take the default"
            )

    def test_every_harness_reports_where_its_agent_templates_live(self) -> None:
        # opencode shipped with template_locations=() while install_targets.py knew
        # its real paths -- two tables disagreeing again. The empty tuple reaches an
        # opencode orchestrator's cli_mode_rules, which other harnesses populate with
        # two real directories, so the orchestrator under-reports where its crew is.
        empty = sorted(h.tool_type for h in HARNESSES if not h.template_locations)
        assert not empty, (
            f"harness(es) {empty} report no agent-template locations to an orchestrator, "
            "while install_targets.py knows where their files go"
        )

    # NAMED, REASONED EXEMPTION -- not a blanket skip (BE-9501).
    #
    # antigravity's two tables disagree and have since before this ticket:
    #   install_targets.INSTALL_PATHS -> ~/.gemini/config/plugins/giljoai/
    #   HARNESSES.template_locations  -> ~/.gemini/antigravity-cli/plugins/giljoai/agents/
    # Different directories, not a formatting difference. Resolving which is
    # authoritative is tracked separately and out of scope here; guessing would risk
    # breaking existing antigravity installs.
    # DELETING this entry IS the fix -- do not widen the exemption to silence a new
    # platform instead.
    _KNOWN_TABLE_DISAGREEMENT = {"antigravity"}

    def test_template_locations_agree_with_the_install_paths_table(self) -> None:
        # The two tables must not drift: whatever a harness TELLS an orchestrator
        # must be where the installer actually PUTS the files.
        for h in HARNESSES:
            if h.tool_type in self._KNOWN_TABLE_DISAGREEMENT:
                continue
            if not h.export_platform or h.export_platform not in INSTALL_PATHS:
                continue
            user_key = _USER_INSTALL_KEY.get(h.export_platform)
            if not user_key:
                continue
            user_path = INSTALL_PATHS[h.export_platform][user_key]
            assert any(user_path in loc for loc in h.template_locations), (
                f"{h.tool_type} installs agents to {user_path} but tells the orchestrator "
                f"{list(h.template_locations)} -- the orchestrator would look in the wrong place"
            )
