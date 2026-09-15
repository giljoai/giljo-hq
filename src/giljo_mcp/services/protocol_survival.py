# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import re
from typing import Any


PROTOCOL_END_MARKER = "END-OF-PROTOCOL"

SECTION_MAX_CHARS = 8_000
SECTION_MAX_LINES = 200


def build_truncation_check(total_chars: int) -> str:
    return (
        f"This response is ~{total_chars} chars. The full_protocol field ends with the "
        f"marker line '{PROTOCOL_END_MARKER}'. If you cannot see that marker at the very "
        "end of full_protocol, your harness truncated this output and you are missing "
        "instructions. Recovery: call get_job_mission again passing the protocol_etag "
        "from this response (the unchanged identity+protocol block is then omitted, "
        "shrinking the response several-fold); if it is still truncated, refetch the "
        "protocol one section at a time with get_job_mission(job_id, section=<name>) — "
        "the protocol_toc field in this response lists every section name and size, and "
        "each section is small enough to survive any known harness limit. Whatever "
        "arrives, the next_required_actions checklist in this response is authoritative "
        "for your immediate next steps."
    )



_BOX_LINE = re.compile(r"^═{10,}\s*$")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    slug = _SLUG_STRIP.sub("_", text.lower()).strip("_")
    return slug[:60] or "section"


def _boundary_name(lines: list[str], i: int) -> str | None:
    line = lines[i].rstrip("\r\n")
    if line.startswith(("## ", "### ")):
        return _slug(line.lstrip("#").strip())
    if _BOX_LINE.match(line) and i + 2 < len(lines):
        title = lines[i + 1].strip()
        if title and _BOX_LINE.match(lines[i + 2].rstrip("\r\n")):
            return _slug(title)
    return None


def _pack_within_budget(name: str, content: str) -> list[tuple[str, str]]:
    if len(content) <= SECTION_MAX_CHARS and len(content.splitlines()) <= SECTION_MAX_LINES:
        return [(name, content)]
    chunks: list[str] = []
    buf: list[str] = []
    buf_chars = 0
    for raw_line in content.splitlines(keepends=True):
        pieces = [raw_line[i : i + SECTION_MAX_CHARS] for i in range(0, len(raw_line), SECTION_MAX_CHARS)] or [""]
        for piece in pieces:
            if buf and (buf_chars + len(piece) > SECTION_MAX_CHARS or len(buf) + 1 > SECTION_MAX_LINES):
                chunks.append("".join(buf))
                buf, buf_chars = [], 0
            buf.append(piece)
            buf_chars += len(piece)
    if buf:
        chunks.append("".join(buf))
    return [(f"{name}.{k}", chunk) for k, chunk in enumerate(chunks, start=1)]


def split_protocol_sections(full_protocol: str) -> list[tuple[str, str]]:
    if not full_protocol:
        return []
    lines = full_protocol.splitlines(keepends=True)
    boundaries: list[tuple[int, str]] = []
    offset = 0
    for i, line in enumerate(lines):
        name = _boundary_name(lines, i)
        if name is not None:
            boundaries.append((offset, name))
        offset += len(line)
    if not boundaries or boundaries[0][0] > 0:
        boundaries.insert(0, (0, "preamble"))
    raw_sections: list[tuple[str, str]] = []
    for idx, (start, name) in enumerate(boundaries):
        end = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(full_protocol)
        raw_sections.append((name, full_protocol[start:end]))
    sections: list[tuple[str, str]] = []
    seen: dict[str, int] = {}
    for name, content in raw_sections:
        seen[name] = seen.get(name, 0) + 1
        unique = name if seen[name] == 1 else f"{name}_{seen[name]}"
        sections.extend(_pack_within_budget(unique, content))
    return sections


def build_protocol_toc(sections: list[tuple[str, str]]) -> list[dict[str, Any]]:
    return [{"section": name, "chars": len(content), "lines": len(content.splitlines())} for name, content in sections]


def finalize_mission_wire_fields(mission_response: Any, caller_etag: str | None, section: str = "") -> None:
    from giljo_mcp.exceptions import ValidationError
    from giljo_mcp.services.mission_assembly import compute_protocol_etag

    if mission_response.full_protocol is not None:
        mission_response.full_protocol += f"\n\n{PROTOCOL_END_MARKER}"
    computed_etag = compute_protocol_etag(mission_response.agent_identity, mission_response.full_protocol)
    mission_response.protocol_etag = computed_etag
    if section and mission_response.full_protocol is not None:
        sections = split_protocol_sections(mission_response.full_protocol)
        content = dict(sections).get(section)
        if content is None:
            raise ValidationError(
                f"Unknown protocol section '{section}'. Valid section names for this mission: "
                f"{[name for name, _ in sections]}. Omit the section parameter for the full response."
            )
        mission_response.protocol_toc = build_protocol_toc(sections)
        mission_response.protocol_section = section
        mission_response.protocol_section_content = content
        mission_response.mission = None
        mission_response.agent_identity = None
        mission_response.full_protocol = None
        mission_response.current_team_state = None
        return
    if caller_etag is not None and caller_etag == computed_etag:
        mission_response.agent_identity = None
        mission_response.full_protocol = None
        mission_response.protocol_unchanged = True
    elif mission_response.full_protocol is not None:
        total_chars = (
            len(mission_response.mission or "")
            + len(mission_response.agent_identity or "")
            + len(mission_response.full_protocol)
        )
        mission_response.truncation_check = build_truncation_check(total_chars)
        mission_response.protocol_toc = build_protocol_toc(split_protocol_sections(mission_response.full_protocol))


def staging_orchestrator_actions(project: Any, chain_ctx: Any) -> list[str] | None:
    return compute_next_required_actions(
        job_type="orchestrator",
        phase="implementation" if getattr(project, "implementation_launched_at", None) is not None else "staging",
        is_chain_member=chain_ctx is not None and getattr(chain_ctx, "role", None) == "sub_orchestrator",
        is_chain_conductor=False,
    )


def compute_next_required_actions(
    *,
    job_type: str | None,
    phase: str | None,
    is_chain_member: bool = False,
    is_chain_conductor: bool = False,
) -> list[str] | None:
    if job_type != "orchestrator":
        return _worker()
    if is_chain_conductor:
        return _conductor()
    if is_chain_member:
        if phase == "staging":
            return _chain_suborch_staging()
        if phase == "implementation":
            return _chain_suborch_implementation()
        return None
    if phase == "staging":
        return _solo_orchestrator_staging()
    if phase == "implementation":
        return _solo_orchestrator_implementation()
    return None


def _worker() -> list[str]:
    return [
        "1. This response IS your mission. Read the mission and full_protocol fields fully.",
        "2. Publish your full TODO plan: report_progress(job_id, todo_items=[...]).",
        "3. Do the work; call report_progress after each completed TODO item.",
        "4. If blocked or needing a decision: post_to_thread on your coordination thread "
        "(requires_action=true), then set_agent_status(job_id, 'blocked', reason).",
        "5. When ALL TODOs are done: complete_job(job_id, result={summary, artifacts, commits}).",
    ]


def _conductor() -> list[str]:
    return [
        "1. You are the project-less chain CONDUCTOR: you sequence projects; you own no project "
        "and spawn no workers yourself.",
        "2. Spawn the CURRENT project's sub-orchestrator per CH_CHAIN_DRIVE STEP A.",
        "3. Poll get_workflow_status(project_id) until ready_to_advance=true — the server's ONE "
        "authoritative advance signal (ignore progress_percent/current_stage).",
        "4. Between polls, check the Hub thread (get_thread_history) for sub-orchestrator escalations and answer them.",
        "5. On ready_to_advance: advance to the next project in resolved_order and repeat from step 2.",
        "6. After the LAST project closes out: complete_job(job_id, ...) — the chain finale.",
    ]


def _chain_suborch_staging() -> list[str]:
    return [
        "1. Read the CHAIN MISSION contract (in CH_SUB_ORCHESTRATOR / via get_context), then author "
        "YOUR project mission: update_project_mission(project_id, ...).",
        "2. spawn_job your agent team. Workers stay INERT until staging ends — do NOT launch them yet.",
        "3. End staging: complete_job(job_id, ...) (staging-end).",
        "4. Post a 'staging-complete' note to the Hub thread (find it: get_context(categories=['chain']) "
        "-> hub_thread_id).",
        "5. Call get_job_mission ONCE, passing the protocol_etag from this response — it returns your "
        "implementation protocol immediately (no gate, no human, no sleep-poll).",
    ]


def _chain_suborch_implementation() -> list[str]:
    return [
        "1. Launch and drive your spawned agents to completion; monitor with get_workflow_status(project_id).",
        "2. Verify deliverables (get_agent_result) and finalize_job each accepted agent.",
        "3. complete_job(job_id, ...) FIRST — it closes your orchestrator execution so the closeout "
        "readiness gate passes.",
        "4. THEN write_project_closeout(project_id, ...) (commit SHA) — its RETURN stamps the "
        "conductor's advance gate; never skip it or the chain stalls.",
        "5. ONLY AFTER write_project_closeout returns, post DONE to the Hub thread, then stop.",
    ]


def _solo_orchestrator_staging() -> list[str]:
    return [
        "1. Read project + product context: get_context(product_id, categories=[...]).",
        "2. Author the project mission: update_project_mission(project_id, ...).",
        "3. spawn_job your agent team (deliverable agents only during staging — no tester/reviewer).",
        "4. End staging: complete_job(job_id, ...) — the server marks the project staging_complete.",
        "5. STOP. The user clicks Implement in the dashboard to start the implementation phase.",
    ]


def _solo_orchestrator_implementation() -> list[str]:
    return [
        "1. Read live team state: get_workflow_status(project_id).",
        "2. Drive your agents to completion; answer their coordination-thread posts (get_thread_history).",
        "3. Verify deliverables (get_agent_result) and finalize_job each accepted agent.",
        "4. complete_job(job_id, ...) — your own orchestrator closeout.",
        "5. write_project_closeout(project_id, ...) (commit SHA + decisions) to finish the project.",
    ]




def build_spawn_footer(*, phase: str | None) -> str:
    if phase == "implementation":
        return (
            "Done: a new agent row now appears in the dashboard JobsTab / team roster "
            "(agent:created). Implementation is live, so this agent is ready to launch "
            "(multi_terminal: its Play button is available). Drive it to completion and "
            "monitor with get_workflow_status(project_id)."
        )
    return (
        "Done: a new agent row now appears in the dashboard JobsTab / team roster "
        "(agent:created). During staging this agent stays INERT (staged/waiting) — do NOT "
        "launch it yet. Finish spawning your team, then end staging with complete_job; the "
        "workers activate when implementation begins."
    )


def build_mission_update_footer(*, phase: str | None) -> str:
    if phase == "implementation":
        return (
            "Done: the dashboard's project mission panel refreshes live "
            "(project:mission_updated). Implementation is already underway, so this is a "
            "mid-flight mission refinement — no phase change; keep driving your agents."
        )
    return (
        "Done: the dashboard's project mission panel refreshes live "
        "(project:mission_updated). Next: spawn_job your agent team (deliverable agents only "
        "during staging), then end staging with complete_job."
    )


def build_complete_job_footer(
    *,
    phase: str,
    is_conductor: bool = False,
    is_chain_member_suborch: bool = False,
) -> str:
    if phase == "staging_end":
        if is_conductor:
            return (
                "Done: chain staging marked complete (staging_end) — the project header flips "
                "to staging-complete. You are the chain CONDUCTOR: HALT and wait for the user's "
                "explicit GO before advancing the chain. Do NOT auto-drive."
            )
        if is_chain_member_suborch:
            return (
                "Done: staging marked complete (staging_end) — the project header flips to "
                'staging-complete and your orchestrator chip shows "waiting" (NOT complete; the '
                "same execution resumes at implementation). This is a CHAIN member: the dashboard "
                "has ALREADY advanced to implementation — there is NO human Implement click. Do "
                "NOT wait for a human; call get_job_mission (pass your protocol_etag) to pick up "
                "your implementation protocol now."
            )
        return (
            "Done: staging marked complete (staging_end) — the project header flips to "
            'staging-complete and your orchestrator chip shows "waiting" (NOT complete; the same '
            "execution resumes at implementation). The Implement (play) button is now unlocked. "
            "STOP this session; a human presses Implement to start the implementation session. Do "
            "NOT write the closeout from this staging session."
        )
    if phase == "closeout":
        if is_conductor:
            return (
                "Done: chain conductor job completed (closeout) — the chain is finished and you "
                "own no project to close. Ensure the series summary is written "
                "(write_memory_entry), then you are done."
            )
        return (
            "Done: orchestrator closeout recorded (closeout) — your orchestrator chip flips to "
            "complete and the project's CloseoutModal readiness advances. Next: call "
            "write_project_closeout (orchestrators coordinate; they do not commit code)."
        )
    return (
        "Done: deliverable recorded (deliverable) — your agent row flips to complete (green) at "
        "100% in the dashboard. No further action: the orchestrator reviews your result "
        "(get_agent_result) and closes your job."
    )
