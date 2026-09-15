# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.unit.neutrality_guard_baseline import BASELINE


REPO_ROOT = Path(__file__).resolve().parents[2]


SCAN_FILES = [
    "src/giljo_mcp/template_seeder.py",
    "src/giljo_mcp/prompt_generation/serena_instructions.py",
    "src/giljo_mcp/services/product_tuning_service.py",
    "src/giljo_mcp/config/defaults.py",
    "src/giljo_mcp/tools/giljo_guide.py",
    "src/giljo_mcp/tools/setup_instructions.py",
    "src/giljo_mcp/tools/slash_command_templates.py",
    "src/giljo_mcp/tools/vision_analysis.py",
    "api/endpoints/ai_tools.py",
]

SCAN_GLOBS = [
    "src/giljo_mcp/services/protocol_sections/*.py",
    "src/giljo_mcp/tools/context_tools/*.py",
    "src/giljo_mcp/prompts/*.py",
    "src/giljo_mcp/tools/*.py",
    "api/endpoints/mcp_tools/*.py",
]

SCAN_EXCLUDE_NAMES = {
    "claude_prompt_builder.py",
    "codex_prompt_builder.py",
    "launch_command_synth.py",
    "multi_terminal_prompt_builder.py",
    "_prelaunch_workproduct_detector.py",
    "_inline_approval.py",
    "_canonical_tool_list.py",
}


def resolve_scan_paths() -> list[Path]:
    paths: list[Path] = [REPO_ROOT / rel for rel in SCAN_FILES]
    for pattern in SCAN_GLOBS:
        for p in sorted(REPO_ROOT.glob(pattern)):
            if p.name in SCAN_EXCLUDE_NAMES or p.name == "__pycache__":
                continue
            paths.append(p)
    missing = [p for p in paths if not p.is_file()]
    assert not missing, f"Neutrality guard scan list has missing files: {missing}"
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique




@dataclass(frozen=True)
class GuardPattern:
    pattern_id: str
    regex: re.Pattern
    hint: str
    keep: tuple[re.Pattern, ...] = field(default_factory=tuple)
    keep_nearby: tuple[re.Pattern, ...] = field(default_factory=tuple)
    min_string_len: int = 0


_NEARBY_WINDOW = 3


def _p(expr: str) -> re.Pattern:
    return re.compile(expr)


_BRAND = r"(?:GiljoAI|Giljo HQ)"


PATTERNS: tuple[GuardPattern, ...] = (
    GuardPattern(
        "role2_target_product",
        _p(
            rf"(?i)(?:\b(?:specialist|tester|reviewer|expert|engineer|developer)s?\s+for\s+{_BRAND}"
            rf"|software you are \w+ is {_BRAND}"
            rf"|test infrastructure of {_BRAND}"
            rf"|the (?:testing|implementation|documentation) specialist for {_BRAND}"
            r"|\b(?:test(?:s|ing)?|improv(?:e|es|ing)|maintain(?:s|ing)?|refactor(?:s|ing)?|debug(?:s|ging)?)"
            rf"\b(?:\s+\w+){{0,3}}\s+{_BRAND}\b"
            rf"|\b{_BRAND}\b(?:\s+\(?MCP\)?)?(?:'s)?\s+(?:codebase|test\s+suite|source)\b)"
        ),
        "GiljoAI named as the TARGET product/software-under-test. Customer "
        "agents work on the customer's product — reword to the generic "
        "product, or platform-brand it ('agent powered by Giljo HQ').",
        keep=(
            _p(rf"(?i)orchestrator agent for {_BRAND}"),
            _p(rf"(?i)agent (?:from|of) {_BRAND}"),
            _p(rf"(?i)powered by {_BRAND}"),
        ),
    ),
    GuardPattern(
        "role3_edition_rules",
        _p(
            r"(?i)(?:tests/saas"
            r"|import from `?saas/"
            r"|edition boundar|edition isolation"
            r"|\bCE tests\b|\bSaaS tests?\b|SaaS test failures"
            r"|between CE and SaaS)"
        ),
        "THIS repo's CE/SaaS edition-isolation rules asserted to customer "
        "agents. Customer products have no CE/SaaS split — remove or make "
        "it product-derived.",
    ),
    GuardPattern(
        "role3_tenant_rule",
        _p(
            r"(?i)(?:verify `?tenant_key`? filtering"
            r"|must (?:filter|verify) (?:by )?`?tenant_key`?"
            r"|tenant isolation verification|strict tenant isolation"
            r"|cross-tenant data never|tenant_a is invisible)"
        ),
        "THIS repo's tenant-isolation discipline stated as a rule for the "
        "customer's code. Customer products may be single-tenant — derive "
        "test rules from the product's own context.",
        min_string_len=40,
    ),
    GuardPattern(
        "role3_ticket_refs",
        _p(
            r"\b(?:BE|FE|INF|IMP|SEC|TSK|ADR|CHT)-\d{3,}[a-z]?\b"
            r"|\bHandover 0\d{2,3}[a-z]?\b"
            r"|\bIssue 0\d{3}(?:-\d)?\b"
        ),
        "Internal ticket/handover reference leaking into customer-rendered "
        "text. Customers cannot dereference these — delete the citation.",
        keep=(
            _p(r"taxonomy_alias"),
        ),
        keep_nearby=(_p(r"(?i)numeric serial"),),
    ),
    GuardPattern(
        "role3_repo_file_rules",
        _p(r"alembic\.ini|CLAUDE\.md|pyproject\.toml"),
        "THIS repo's protected files listed as if they exist in the "
        "customer's repo. Make the protected-zone list product-derived.",
        keep=(
            _p(r"(?i)agents\.md"),
        ),
        min_string_len=20,
    ),
    GuardPattern(
        "role3_handover_docs",
        _p(r"(?i)handover doc"),
        "'Handover documents' are an internal process artifact, not a "
        "customer deliverable — reword to plain project documentation.",
    ),
    GuardPattern(
        "toolchain_backend_mandate",
        _p(r"(?i)\bpytest\b|\bruff\b|\bconftest\b|tests/(?:unit|integration)/"),
        "Python-only toolchain (pytest/ruff/conftest) mandated to customer "
        "agents whose product may be Go/Node/Rust/etc. Derive the test and "
        "lint commands from the product's tech stack.",
    ),
    GuardPattern(
        "toolchain_frontend_mandate",
        _p(r"(?i)\bvitest\b|\bplaywright\b|@vue/test-utils|@pinia/testing|\bjsdom\b|npm run test:run"),
        "Vue/Vitest-specific frontend toolchain mandated to customer agents. Derive from the product's tech stack.",
    ),
    GuardPattern(
        "toolchain_mandate_misc",
        _p(r"(?i)use pathlib|real PostgreSQL|\b80% lines|\b75% branches|coverage >= ?80"),
        "THIS repo's language/database/coverage specifics stated as universal mandates. Make them product-derived.",
    ),
    GuardPattern(
        "stack_examples_this_repo",
        _p(r"(?i)Postgres JSONB|\bEventBus\b|\bAlembic\b(?!\.ini)|\bSQLAlchemy\b"),
        "Example prose presumes THIS repo's stack (Postgres/Alembic/EventBus/SQLAlchemy). Use stack-neutral examples.",
    ),
    GuardPattern(
        "githost_hardcoded",
        _p(r"(?i)\bgithub\b|\bgitea\b"),
        "Hardcoded git host. Customer repos may live anywhere — keep git "
        "features host-neutral (our own update feed github.com/giljoai/* "
        "is allowlisted).",
        keep=(_p(r"(?i)github\.com/giljoai"),),
    ),
    GuardPattern(
        "branch_literal",
        _p(r"(?i)\borigin/master\b|\bmaster branch\b|\bmaster bug\b|\bpush to master\b"),
        "'master' assumed as THE branch. Customer repos use main/trunk/"
        "release branches — say 'the default branch' or derive it.",
    ),
    GuardPattern(
        "os_shell_literal",
        _p(r"(?i)\bPowerShell\b|\bpwsh\b|\bcmd /k\b|Windows Terminal"),
        "Windows-only shell/terminal presented as the only option. Offer a "
        "conditional per-OS form (detect-shell ladder or Linux/macOS + "
        "Windows pair).",
        keep=(
            _p(r"(?i)if shell contains"),
            _p(r"(?i)\bbash\b|\bzsh\b|(?:^\s*[-*]?\s*|^\s*\|\s*|:[^|]*\s\|\s*)(?:linux|macos)[^:]{0,20}:"),
            _p(r"(?i)windows powershell:"),
            _p(r"(?i)- windows \(windows terminal\):"),
            _p(r"^\s*wt -w \d+ new-tab"),
        ),
        keep_nearby=(
            _p(r"(?i)\bbash\b|\bzsh\b|(?:^\s*[-*]?\s*|^\s*\|\s*|:[^|]*\s\|\s*)(?:linux|macos)[^:]{0,20}:|`sleep \d"),
        ),
    ),
    GuardPattern(
        "harness_tool_names",
        _p(r"\bTodoWrite\b|\bToolSearch\b"),
        "Claude-Code-specific tool name emitted to every harness. Gate it "
        "('Claude Code: ...') or use a harness-neutral phrasing "
        "('your task-list tool').",
        keep=(_p(r"(?i)claude code"),),
        keep_nearby=(_p(r"(?i)claude code"),),
    ),
    GuardPattern(
        "serena_python_only_claim",
        _p(r"(?i)python-only in this project"),
        "Asserts the Serena LSP is Python-only — true for THIS repo, false "
        "for customer products in other languages. Derive from the "
        "product's tech stack.",
    ),
)




@dataclass(frozen=True)
class Hit:
    file: str
    line: int
    pattern_id: str
    text: str

    @property
    def fingerprint(self) -> str:
        norm = " ".join(self.text.split())
        raw = f"{self.file}|{self.pattern_id}|{norm}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _docstring_node_ids(tree: ast.Module) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def iter_string_constants(source: str) -> list[tuple[int, list[str]]]:
    tree = ast.parse(source)
    skip = _docstring_node_ids(tree)
    out: list[tuple[int, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            out.append((node.lineno, node.value.split("\n")))
    return out


def match_prose_line(
    line: str,
    string_len: int | None = None,
    window: list[str] | None = None,
) -> list[str]:
    effective_len = len(line) if string_len is None else string_len
    nearby = window if window is not None else [line]
    fired: list[str] = []
    for pat in PATTERNS:
        if effective_len < pat.min_string_len:
            continue
        if not pat.regex.search(line):
            continue
        if any(k.search(line) for k in pat.keep):
            continue
        if any(k.search(w) for k in pat.keep_nearby for w in nearby):
            continue
        fired.append(pat.pattern_id)
    return fired


def scan_file(path: Path) -> list[Hit]:
    rel = path.relative_to(REPO_ROOT).as_posix()
    source = path.read_text(encoding="utf-8")
    hits: list[Hit] = []
    for start_lineno, lines in iter_string_constants(source):
        total_len = sum(len(ln) for ln in lines)
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            window = lines[max(0, i - _NEARBY_WINDOW) : i + _NEARBY_WINDOW + 1]
            for pattern_id in match_prose_line(line, string_len=total_len, window=window):
                hits.append(Hit(rel, start_lineno + i, pattern_id, line.strip()))
    return hits


def scan_all() -> list[Hit]:
    hits: list[Hit] = []
    for path in resolve_scan_paths():
        hits.extend(scan_file(path))
    return hits


def _hint_for(pattern_id: str) -> str:
    for pat in PATTERNS:
        if pat.pattern_id == pattern_id:
            return pat.hint
    return ""


def format_report(hits: list[Hit]) -> str:
    lines = ["", "NEUTRALITY GUARD — new dogfooding contamination detected:", ""]
    by_pattern: dict[str, list[Hit]] = {}
    for h in hits:
        by_pattern.setdefault(h.pattern_id, []).append(h)
    for pattern_id in sorted(by_pattern):
        group = by_pattern[pattern_id]
        lines.append(f"[{pattern_id}] ({len(group)} hits)")
        lines.append(f"  fix: {_hint_for(pattern_id)}")
        for h in group:
            lines.append(f"    {h.file}:{h.line}  fp={h.fingerprint}")
            lines.append(f"      {h.text[:160]}")
        lines.append("")
    lines.append(
        "If a hit is a FALSE positive (Role-1 branding or a conditional "
        "per-OS/per-harness block), extend the pattern's keep-regexes with a "
        "unit case. Only baseline a TRUE offender you cannot fix now: add "
        '(fingerprint, "file :: pattern :: excerpt") to '
        "tests/unit/neutrality_guard_baseline.py."
    )
    return "\n".join(lines)




def test_no_new_dogfooding_contamination():
    baseline_fps = {fp for fp, _note in BASELINE}
    new_hits = [h for h in scan_all() if h.fingerprint not in baseline_fps]
    assert not new_hits, format_report(new_hits)


def test_baseline_has_no_stale_entries():
    observed = {h.fingerprint for h in scan_all()}
    stale = [(fp, note) for fp, note in BASELINE if fp not in observed]
    detail = "\n".join(f"  {fp}  {note}" for fp, note in stale)
    assert not stale, (
        "\nBaseline entries no longer observed (offender cleaned or line "
        "edited). Remove them from neutrality_guard_baseline.py:\n" + detail
    )


def test_baseline_has_no_duplicate_fingerprints():
    fps = [fp for fp, _note in BASELINE]
    assert len(fps) == len(set(fps)), "Duplicate fingerprints in baseline"


def test_scan_surface_is_alive():
    paths = resolve_scan_paths()
    assert len(paths) >= 50, (
        f"Neutrality guard scan surface collapsed to {len(paths)} files (expected >= 50). "
        "A glob has stopped matching or an exclusion is too broad — the guard is "
        "examining almost nothing and will pass vacuously."
    )

    for pattern in SCAN_GLOBS:
        matched = [p for p in REPO_ROOT.glob(pattern) if p.name not in SCAN_EXCLUDE_NAMES]
        assert matched, f"SCAN_GLOB {pattern!r} matched no files — the scanned surface silently shrank."

    for name in SCAN_EXCLUDE_NAMES:
        assert any(REPO_ROOT.glob(f"**/{name}")), (
            f"SCAN_EXCLUDE_NAMES entry {name!r} matches no file in the repo — remove the stale exclusion."
        )

    scanned_lines = 0
    for path in paths:
        for _start, lines in iter_string_constants(path.read_text(encoding="utf-8")):
            scanned_lines += sum(1 for ln in lines if ln.strip())
    assert scanned_lines >= 3000, (
        f"Only {scanned_lines} string-constant lines scanned (expected >= 3000). "
        "The scanner resolves files but is not extracting prose from them."
    )


def test_guard_catches_a_planted_violation_end_to_end(tmp_path, monkeypatch):
    for rel in SCAN_FILES:
        stub = tmp_path / rel
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text("CLEAN = 'nothing to see here'\n", encoding="utf-8")

    planted = tmp_path / "src/giljo_mcp/tools/planted_offender.py"
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(
        'TEMPLATE = """\nDo not close the project until BE-1234 lands.\n"""\n',
        encoding="utf-8",
    )

    monkeypatch.setattr("tests.unit.test_neutrality_guard.REPO_ROOT", tmp_path)
    hits = scan_all()

    planted_hits = [h for h in hits if h.file.endswith("planted_offender.py")]
    assert planted_hits, "Guard went blind: a planted ticket ref in a scanned glob produced no hit."
    assert planted_hits[0].pattern_id == "role3_ticket_refs"
    assert planted_hits[0].fingerprint not in {fp for fp, _note in BASELINE}



KEEP_CASES = [
    "You are the Orchestrator Agent for Giljo HQ.",
    "You are an agent powered by Giljo HQ coordinating this project.",
    "This message comes from an agent from Giljo HQ.",
    "You are the Orchestrator Agent for GiljoAI MCP.",
    "You are an agent powered by GiljoAI MCP coordinating this project.",
    "Use spawn_job, get_context, and giljo_guide to drive the workflow.",
    "Invoke the /giljo skill before creating projects or tasks.",
    'Set execution_mode to "claude_code" to launch a terminal session.',
    "Release feed: https://github.com/giljoai/GiljoAI_MCP/releases/latest",
    '- If shell contains "powershell" or "pwsh":',
    'Linux/macOS: python3 -c "import json; ..." | Windows PowerShell: $p = ...',
    "Ensure cross-platform compatibility (Windows, macOS, Linux)",
    "Claude Code: Use TodoWrite tool to track workflow progress.",
    "Claude Code only — load schemas via ToolSearch before calling them.",
    "Windows PowerShell: $env:USERPROFILE setup one-liner (paired with the Linux/macOS line above)",
    "GiljoAI helps agents test the customer's codebase.",
    "| Linux: use gnome-terminal | Windows: use Windows Terminal |",
    "PowerShell: Get-Content -Wait log.txt | Linux: tail -f log.txt",
]


@pytest.mark.parametrize("text", KEEP_CASES)
def test_keep_list_never_trips(text: str):
    assert match_prose_line(text) == [], f"Keep-list text wrongly flagged: {text!r}"



TRIP_CASES = [
    ("Testing specialist for Giljo HQ with strict TDD.", "role2_target_product"),
    ("The software you are improving is Giljo HQ.", "role2_target_product"),
    ("Write comprehensive tests for Giljo HQ.", "role2_target_product"),
    ("You are improving the Giljo HQ codebase.", "role2_target_product"),
    ("The GiljoAI codebase you are testing has strict conventions.", "role2_target_product"),
    ("Please maintain Giljo HQ's test suite going forward.", "role2_target_product"),
    ("Testing specialist for GiljoAI MCP with strict TDD.", "role2_target_product"),
    ("You are improving the GiljoAI MCP codebase.", "role2_target_product"),
    ("SaaS tests live in tests/saas/ only.", "role3_edition_rules"),
    ("Every DB query must filter by tenant_key without exception here.", "role3_tenant_rule"),
    ("Do not use blocked status — that predates BE-5029.", "role3_ticket_refs"),
    ("Sync your TODO list with the dashboard (Handover 0392).", "role3_ticket_refs"),
    ("Never edit alembic.ini without approval.", "role3_repo_file_rules"),
    ("Update handover documents with implementation notes.", "role3_handover_docs"),
    ("Run python -m pytest tests/ -v and report the output.", "toolchain_backend_mandate"),
    ("Run npx vitest run and report real pass/fail output.", "toolchain_frontend_mandate"),
    ("Integration tests should hit real PostgreSQL where possible.", "toolchain_mandate_misc"),
    ("Record it like: chose Postgres JSONB over a separate audit table.", "stack_examples_this_repo"),
    ("Fetch commit history when GitHub integration is enabled.", "githost_hardcoded"),
    ("Cherry-pick the fix onto origin/master before closing.", "branch_literal"),
    ("Open PowerShell and paste the command below.", "os_shell_literal"),
    ("Unlike Linux, you must always use PowerShell for this step.", "os_shell_literal"),
    ("Even on macOS you must always launch PowerShell for this step.", "os_shell_literal"),
    ("Unlike Linux: you must always use PowerShell for this step.", "os_shell_literal"),
    (
        "Use cmd | Linux: to filter, but you must always use PowerShell for this actual step.",
        "os_shell_literal",
    ),
    ("Create your TodoWrite task list before implementation.", "harness_tool_names"),
    ("Serena's LSP is Python-only in this project.", "serena_python_only_claim"),
]


@pytest.mark.parametrize("text,expected_pattern", TRIP_CASES)
def test_trip_cases_fire(text: str, expected_pattern: str):
    fired = match_prose_line(text)
    assert expected_pattern in fired, f"Guard went blind: {text!r} did not fire {expected_pattern}"


def test_min_string_len_gate_filters_short_code_literals():
    assert match_prose_line("tenant_key", string_len=10) == []
    long_line = "- Every test involving DB queries must verify `tenant_key` filtering."
    assert "role3_tenant_rule" in match_prose_line(long_line, string_len=500)


def test_synthetic_injection_detected(tmp_path: Path):
    probe = tmp_path / "synthetic_probe.py"
    probe.write_text(
        'TEMPLATE = """\n'
        "You are the testing specialist for Giljo HQ.\n"
        "Open PowerShell and run the commands from the GitHub repo.\n"
        '"""\n',
        encoding="utf-8",
    )
    source = probe.read_text(encoding="utf-8")
    rel_hits = []
    for _start, lines in iter_string_constants(source):
        total_len = sum(len(ln) for ln in lines)
        for line in lines:
            if line.strip():
                rel_hits.extend(match_prose_line(line, string_len=total_len))
    assert "role2_target_product" in rel_hits
    assert "os_shell_literal" in rel_hits
    assert "githost_hardcoded" in rel_hits
