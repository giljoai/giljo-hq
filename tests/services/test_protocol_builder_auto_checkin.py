# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for the orchestrator check-in protocol (Handover 0904/0960, BE-6013, FE-9296b).

FE-9296b retired the per-project cadence slider and rewrote CH6 around the
BE-9296a wake mechanism. The contract these tests pin:

1. CH6 branches on harness wake capability: PATH A parks on get_my_turn
   (wake-capable, verified Claude Code CLI), PATH B is the timed sleep loop
   (everything else; chat surfaces can never hold the wake call open).
2. The live-value discipline survives the slider: the cadence is re-read each
   cycle from get_workflow_status().checkin_cadence_minutes; the interval arg
   is a first-cycle seed only, never baked as an authoritative sleep number.
3. Status honesty: PATH A sets wake_on_signal, PATH B sets wake_in_minutes.
4. The gate is ONE behaviour: CH6 renders for every non-CLI orchestrator
   regardless of the (retired) auto_checkin_enabled flag, matching the
   get_job_mission path; CLI modes never receive it.
5. The project-less chain conductor gets its own CH6 variant (account-level
   cadence applied to the chain-drive wait).
"""

import re

from giljo_mcp.services.protocol_builder import (
    _build_ch6_auto_checkin,
    _build_orchestrator_protocol,
)


class TestCh6WakeCapabilityBranch:
    """CH6 must branch exactly on harness wake capability (FE-9296b / BE-9296a)."""

    def test_ch6_carries_both_paths(self):
        ch6 = _build_ch6_auto_checkin(interval=10)
        assert "PATH A" in ch6
        assert "PATH B" in ch6
        # BE-9554: get_my_turn merged into get_my_turn(wait_seconds=). The guarantee
        # is unchanged -- ch6 must teach the BLOCKING wake path. Asserted as both
        # tokens rather than one literal: the rendered call carries agent_id between
        # them, so a literal substring would pin formatting instead of behaviour.
        assert "get_my_turn" in ch6 and "wait_seconds" in ch6

    def test_ch6_names_the_verified_wake_harness(self):
        # BE-9296a DoD item 10: the wake was OBSERVED on Claude Code CLI only —
        # the prose must anchor capability to that record, not guess per harness.
        ch6 = _build_ch6_auto_checkin(interval=10)
        assert "Claude Code CLI" in ch6

    def test_ch6_states_chat_surfaces_can_never_hold_the_wake_call(self):
        ch6 = _build_ch6_auto_checkin(interval=10)
        assert "claude.ai" in ch6 and "chatgpt.com" in ch6
        assert "NEVER" in ch6
        lowered = ch6.lower()
        assert "polling is their primary path" in lowered

    def test_ch6_wake_path_falls_back_on_waiter_limit(self):
        ch6 = _build_ch6_auto_checkin(interval=10)
        assert "waiter_limit" in ch6

    def test_ch6_wake_path_keeps_the_cadence_as_a_heartbeat(self):
        # Status changes don't fire the wake signal, so PATH A must still run a
        # full coordination pass every M minutes.
        ch6 = _build_ch6_auto_checkin(interval=10)
        lowered = ch6.lower()
        assert "do not" in lowered and "fire the wake signal" in lowered


class TestCh6LiveReadContract:
    """The live-value rule (BE-6013) survives the slider's retirement."""

    def test_ch6_reads_the_resolved_cadence_from_get_workflow_status(self):
        ch6 = _build_ch6_auto_checkin(interval=10)
        assert "get_workflow_status" in ch6
        assert "checkin_cadence_minutes" in ch6

    def test_ch6_states_remembered_values_are_not_authoritative(self):
        ch6 = _build_ch6_auto_checkin(interval=10)
        lowered = ch6.lower()
        assert "not authoritative" in lowered
        assert "remember" in lowered

    def test_ch6_does_not_bake_a_single_authoritative_sleep_number(self):
        """Regression guard: the OLD pattern baked `sleep 600` / `Start-Sleep -Seconds 600`."""
        for interval in (5, 10, 30, 60):
            ch6 = _build_ch6_auto_checkin(interval=interval)
            baked_seconds = interval * 60
            assert f"sleep {baked_seconds}" not in ch6, (
                f"CH6 must not bake a literal `sleep {baked_seconds}` (interval={interval})"
            )
            assert f"Start-Sleep -Seconds {baked_seconds}" not in ch6, (
                f"CH6 must not bake `Start-Sleep -Seconds {baked_seconds}` (interval={interval})"
            )

    def test_ch6_instructs_computing_seconds_at_the_agent(self):
        ch6 = _build_ch6_auto_checkin(interval=10)
        assert "seconds = M * 60" in ch6

    def test_ch6_interval_is_only_a_seed(self):
        ch6 = _build_ch6_auto_checkin(interval=10)
        assert "seed" in ch6.lower()

    def test_ch6_interval_defaults_when_omitted(self):
        ch6 = _build_ch6_auto_checkin()
        assert "CH6: CHECK-IN PROTOCOL" in ch6


class TestCh6StatusHonesty:
    """The dashboard indicator derives from the markers CH6 mandates."""

    def test_wake_path_sets_wake_on_signal(self):
        ch6 = _build_ch6_auto_checkin(interval=10)
        assert "wake_on_signal=true" in ch6

    def test_timed_path_sets_wake_in_minutes(self):
        ch6 = _build_ch6_auto_checkin(interval=10)
        assert "wake_in_minutes=M" in ch6
        assert 'set_agent_status(status="sleeping"' in ch6

    def test_ch6_keeps_claude_code_sleep_workaround(self):
        ch6 = _build_ch6_auto_checkin(interval=10)
        assert "sleep 1 N" in ch6 or "sleep 1 <seconds>" in ch6
        assert "CLAUDE CODE NOTE" in ch6

    def test_ch6_keeps_powershell_and_bash_branch(self):
        ch6 = _build_ch6_auto_checkin(interval=10)
        assert "Start-Sleep -Seconds" in ch6
        assert re.search(r"\bsleep\b", ch6)

    def test_ch6_uses_imperative_mandatory_language(self):
        ch6 = _build_ch6_auto_checkin(interval=10)
        assert "MANDATORY EXECUTION" in ch6
        assert "Do NOT ask the user for confirmation" in ch6

    def test_ch6_warns_about_token_consumption(self):
        ch6 = _build_ch6_auto_checkin(interval=10)
        assert "token consumption" in ch6.lower()


class TestCh6ConductorVariant:
    """FE-9296b: the project-less conductor gets a cadence at all (TSK-9324 dec. 5)."""

    def test_conductor_variant_renders_its_own_chapter(self):
        ch6 = _build_ch6_auto_checkin(interval=10, for_conductor=True)
        assert "CHAIN CONDUCTOR" in ch6
        assert "project-less" in ch6

    def test_conductor_variant_carries_the_account_default_seed(self):
        ch6 = _build_ch6_auto_checkin(interval=25, for_conductor=True)
        assert "25 minutes" in ch6

    def test_conductor_variant_branches_on_wake_capability_too(self):
        ch6 = _build_ch6_auto_checkin(interval=10, for_conductor=True)
        # BE-9554: get_my_turn merged into get_my_turn(wait_seconds=). The guarantee
        # is unchanged -- ch6 must teach the BLOCKING wake path. Asserted as both
        # tokens rather than one literal: the rendered call carries agent_id between
        # them, so a literal substring would pin formatting instead of behaviour.
        assert "get_my_turn" in ch6 and "wait_seconds" in ch6
        assert "Claude Code CLI" in ch6

    def test_conductor_variant_keeps_the_advance_gate_poll(self):
        # The wake signal cannot report ready_to_advance (it flips without a Hub
        # post), so the conductor must keep polling get_workflow_status.
        ch6 = _build_ch6_auto_checkin(interval=10, for_conductor=True)
        assert "ready_to_advance" in ch6
        assert "get_workflow_status" in ch6

    def test_both_variants_share_the_marker_prefix(self):
        # test suites detect CH6 presence by this prefix — both variants carry it.
        assert "CH6: CHECK-IN" in _build_ch6_auto_checkin(interval=10)
        assert "CH6: CHECK-IN" in _build_ch6_auto_checkin(interval=10, for_conductor=True)


class TestProtocolCh6Integration:
    """FE-9296b: ONE gate — CH6 renders for every non-CLI orchestrator."""

    def test_protocol_includes_ch6_for_multi_terminal_regardless_of_enabled_flag(self):
        # The enabled flag is retired as a gate: staging and runtime paths must
        # agree (the old split shipped CH6 on one path and not the other).
        for enabled in (True, False):
            protocol = _build_orchestrator_protocol(
                cli_mode=False,
                project_id="test-proj",
                orchestrator_id="test-orch",
                tenant_key="test-tenant",
                auto_checkin_enabled=enabled,
                auto_checkin_interval=10,
            )
            assert "ch6_auto_checkin" in protocol, f"CH6 must render when enabled={enabled}"
            assert "CH6: CHECK-IN" in protocol["ch6_auto_checkin"]
            assert "get_workflow_status" in protocol["ch6_auto_checkin"]

    def test_protocol_excludes_ch6_in_staging_response(self):
        # Phase-gated with CH5: the check-in loop only exists once agents are
        # dispatched, and the staging response has a payload budget (CE-0033)
        # CH6 would breach for no benefit.
        protocol = _build_orchestrator_protocol(
            cli_mode=False,
            project_id="test-proj",
            orchestrator_id="test-orch",
            tenant_key="test-tenant",
            include_implementation_reference=False,
            auto_checkin_enabled=True,
            auto_checkin_interval=10,
        )
        assert "ch6_auto_checkin" not in protocol

    def test_protocol_excludes_ch6_in_cli_mode_even_when_enabled(self):
        protocol = _build_orchestrator_protocol(
            cli_mode=True,
            project_id="test-proj",
            orchestrator_id="test-orch",
            tenant_key="test-tenant",
            auto_checkin_enabled=True,
            auto_checkin_interval=10,
        )
        assert "ch6_auto_checkin" not in protocol

    def test_protocol_ch6_live_read_regardless_of_seed_interval(self):
        protocol = _build_orchestrator_protocol(
            cli_mode=False,
            project_id="test-proj",
            orchestrator_id="test-orch",
            tenant_key="test-tenant",
            auto_checkin_enabled=True,
            auto_checkin_interval=30,
        )
        ch6 = protocol["ch6_auto_checkin"]
        assert "get_workflow_status" in ch6
        assert "sleep 1800" not in ch6
        assert "Start-Sleep -Seconds 1800" not in ch6

    def test_protocol_defaults_include_ch6_for_non_cli(self):
        """Params omitted → CH6 still renders (the account default seeds it)."""
        protocol = _build_orchestrator_protocol(
            cli_mode=False,
            project_id="test-proj",
            orchestrator_id="test-orch",
            tenant_key="test-tenant",
        )
        assert "ch6_auto_checkin" in protocol
