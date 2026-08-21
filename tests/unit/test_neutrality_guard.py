# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Neutrality guard — CI ratchet against dogfooding contamination (BE-9257).

Giljo HQ is developed by driving Giljo HQ against its own codebase
("dogfooding"). That makes it easy for text meant for CUSTOMER agents —
seeded agent templates, protocol sections, staging/mission prompts, setup
instructions, tuning prompts, tool-response labels — to absorb rules that are
true of THIS repository but false for a customer's product. This test scans
the customer-reaching prompt/template surfaces and fails when NEW text of
that kind appears. Known current offenders live in an explicit baseline
(``neutrality_guard_baseline.py``); follow-up projects shrink it to zero.

Role doctrine — what to keep vs what to scrub
=============================================

**Role 1 — GiljoAI as the SYSTEM the agent runs on (KEEP, never flag):**
The platform may brand itself. Examples that must always pass:

1. "You are the Orchestrator Agent for Giljo HQ" (platform identity)
2. "an agent powered by Giljo HQ" / "agent from Giljo HQ" (branding)
3. Tool and skill identifiers: ``spawn_job``, ``get_context``,
   ``giljo_guide``, the ``/giljo`` skill, ``execution_mode="claude_code"``
   as a MODE NAME.

**Role 2 — GiljoAI as the TARGET product / software-under-test (SCRUB):**
Customer agents work on the CUSTOMER's product, never on GiljoAI itself.

1. "Testing specialist for Giljo HQ" (the customer's tester tests the
   customer's product)
2. "the software you are improving is GiljoAI"
3. "maintain the test infrastructure of Giljo HQ"

**Role 3 — THIS repo's internals asserted as customer rules (SCRUB):**
Our conventions are not the customer's conventions.

1. "Every DB query must filter by tenant_key" (our isolation rule)
2. "SaaS tests live in tests/saas/ — CE tests must never import from saas/"
   (our edition layout)
3. "Run python -m pytest / ruff check / npx vitest run" as mandates,
   internal ticket refs (BE-1234, Handover 0392), "origin/master" as THE
   branch, PowerShell/Windows-Terminal as the only shell.

**Deliberately platform/OS-specific text is fine when CONDITIONAL:** a
detect-your-shell ladder ("If shell contains 'powershell' ..."), a dual-OS
pair ("Linux/macOS: ... / Windows PowerShell: ..."), or a block gated on the
Claude Code harness ("Claude Code: use TodoWrite ...") — the per-pattern
keep-regexes below encode exactly these shapes.

Mechanics
=========
- Scans STRING LITERALS ONLY, via AST: every non-docstring ``str`` constant
  in the scanned files. Implementation comments and identifiers never fire.
  Module/class/function docstrings are internal developer documentation in
  these modules (the rendered text lives in assigned template constants) and
  are deliberately NOT scanned — including them floods the guard with
  non-rendered ticket refs.
- A hit's fingerprint is sha256("file|pattern_id|normalized-line-text"), so
  baseline entries survive line-number drift but NOT content edits: touching
  a baselined line without cleaning it makes the hit "new" and the guard RED.
- A baseline entry whose line was actually cleaned turns STALE and the guard
  goes RED until the entry is removed — that is the ratchet direction.
- BE-9264 F4: because the fingerprint has NO line number in it, several
  DISTINCT occurrences that happen to share identical (file, pattern_id,
  normalized-line-text) collapse onto the SAME fingerprint — one baseline
  entry then silently exempts every occurrence with that exact text, not
  just one line. Example: BE-9261 fixed three identical
  ``"file_location": "Terminal/PowerShell",`` lines in
  ``api/endpoints/ai_tools.py`` (the claude/codex/gemini CONFIG_GENERATORS
  entries) — before the fix they shared one fingerprint and would have
  needed only one baseline entry to cover all three. When writing a
  baseline note, say "N occurrences" explicitly rather than implying a
  single line, or a reader will underestimate the offender's spread.
- Platform-dispatch modules whose FUNCTION is per-platform output
  (claude/codex/gemini prompt builders, launch_command_synth,
  multi_terminal_prompt_builder, platform_registry) are excluded by design,
  as is the update-feed client for our own releases (allowlisted
  github.com/giljoai). The product-memory "github" namespace files are
  excluded pending their dedicated de-coupling project (BE-9256).

Parallel-safe: read-only scan, no module-level mutable state, no DB.
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.unit.neutrality_guard_baseline import BASELINE


REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Scan scope — customer-reaching prompt/template/tool-response surfaces.
# Keep this list explicit and easy to extend: add the file, run the test,
# baseline (or better: fix) what fires.

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

# Excluded from the globs above: modules whose FUNCTION is platform-specific
# output (they dispatch per platform/OS by design — flagging them would fight
# their purpose), and the product-memory git-namespace files deferred to the
# git-host de-coupling project (BE-9256).
SCAN_EXCLUDE_NAMES = {
    "claude_prompt_builder.py",
    "codex_prompt_builder.py",
    "gemini_prompt_builder.py",
    "launch_command_synth.py",
    "multi_terminal_prompt_builder.py",
    # BE-9264 F2: the mcp_tools/*.py + tools/*.py glob widening below sweeps in
    # internal logger.warning/logger.error diagnostic strings that never reach
    # an agent (they are process logs, not tool descriptions or prose). These
    # two files are ALL diagnostic-log-only in their scanned string literals
    # (verified by audit, not by function-name pattern like the platform
    # dispatchers above): _prelaunch_workproduct_detector.py (a single
    # fail-open skip-reason log), _inline_approval.py (four async-fallback
    # logs). Baselining log noise would misrepresent it as
    # audited-customer-facing-contamination; excluding the files is the
    # honest fix.
    "_prelaunch_workproduct_detector.py",
    "_inline_approval.py",
    # TSK-9314: the canonical orchestrator tool list. Its ONLY scanned string
    # constants are the mcp tool-name identifiers and the one call template
    # ``ToolSearch(query="...", max_results=25)`` that
    # ``render_toolsearch_call_one_line()`` returns -- there is no prose in
    # this module for the guard to miss. The literal cannot carry a
    # "Claude Code" label of its own without ceasing to be a pasteable call,
    # so it can only ever be baselined or excluded; excluding it matches the
    # platform-dispatch precedent above. Verified at exclusion time, and the
    # check that keeps it honest: all SIX render sites gate the output on the
    # harness -- staging_prompt_builder.py (x2) and template_seeder.py on
    # ``if tool == "claude-code":``, prompts.py on ``if harness_is_claude:``,
    # and claude_prompt_builder.py / multi_terminal_prompt_builder.py are
    # themselves already excluded platform dispatchers. (The prior baseline
    # note claimed a single caller; that was wrong -- the count is six. The
    # conclusion survives the correction because every one of them gates.)
    "_canonical_tool_list.py",
}


def resolve_scan_paths() -> list[Path]:
    paths: list[Path] = [REPO_ROOT / rel for rel in SCAN_FILES]
    for pattern in SCAN_GLOBS:
        for p in sorted(REPO_ROOT.glob(pattern)):
            if p.name in SCAN_EXCLUDE_NAMES or p.name == "__pycache__":
                continue
            paths.append(p)
    # Sanity: every explicit file must exist (a rename must update this list,
    # not silently shrink the scanned surface).
    missing = [p for p in paths if not p.is_file()]
    assert not missing, f"Neutrality guard scan list has missing files: {missing}"
    # De-dupe while preserving order (a glob may overlap an explicit entry).
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


# ---------------------------------------------------------------------------
# Patterns. Each has its OWN keep-regexes: a line matching any keep-regex of
# a pattern is exempt from THAT pattern only (so a dual-OS line suppresses
# the OS hit without hiding a toolchain hit on the same line).


@dataclass(frozen=True)
class GuardPattern:
    pattern_id: str
    regex: re.Pattern
    hint: str
    keep: tuple[re.Pattern, ...] = field(default_factory=tuple)
    # Like keep, but matched against a +/-3-line window INSIDE the same
    # string constant — recognizes line-wrapped conditional shapes (a
    # per-OS ladder, a "Bash: ... / PowerShell: ..." pair split across
    # lines) that a single-line keep-regex cannot see.
    keep_nearby: tuple[re.Pattern, ...] = field(default_factory=tuple)
    # Only fire inside string constants at least this long. Filters short
    # code-facing literals (dict keys, enum values) out of prose-only rules.
    min_string_len: int = 0


_NEARBY_WINDOW = 3


def _p(expr: str) -> re.Pattern:
    return re.compile(expr)


# BE-9361: the Role-2 patterns keyed on the bare literal "GiljoAI". The product
# display name is now "Giljo HQ" (``branding.PRODUCT_NAME``), which does NOT
# contain "GiljoAI" -- so post-rename contamination ("Testing specialist for
# Giljo HQ") would have slipped straight past the guard. Both forms are matched:
# the legacy one stays because un-migrated template rows and older prose still
# carry it. Interpolated into an already-``(?i)`` pattern, so case is covered.
_BRAND = r"(?:GiljoAI|Giljo HQ)"


PATTERNS: tuple[GuardPattern, ...] = (
    GuardPattern(
        "role2_target_product",
        _p(
            rf"(?i)(?:\b(?:specialist|tester|reviewer|expert|engineer|developer)s?\s+for\s+{_BRAND}"
            rf"|software you are \w+ is {_BRAND}"
            rf"|test infrastructure of {_BRAND}"
            rf"|the (?:testing|implementation|documentation) specialist for {_BRAND}"
            # BE-9264 F1: a verb naming the activity, within ~3 words BEFORE
            # GiljoAI ("tests for Giljo HQ", "maintain Giljo HQ's test
            # suite") -- catches phrasing that names GiljoAI as the thing
            # being worked ON without using a "specialist/tester ... for"
            # noun form. Deliberately ONE-DIRECTIONAL (verb-then-GiljoAI
            # only, not GiljoAI-then-verb): a "GiljoAI ... verb" ordering
            # cannot tell "GiljoAI [subject] ... test [object=something
            # else]" apart from "GiljoAI [object of testing]" (advisory from
            # the post-merge audit on PR #589: "GiljoAI helps agents test
            # the customer's codebase" has GiljoAI only 2 words before
            # "test" yet is Role-1-safe prose about the CUSTOMER's codebase,
            # not GiljoAI-as-target). Every existing trip case for this
            # pattern already fires via this verb-before-GiljoAI form or the
            # noun-phrase form below, so dropping the reverse-order half
            # loses no coverage -- see the KEEP_CASES entry below for the
            # regression probe (test_keep_list_never_trips).
            r"|\b(?:test(?:s|ing)?|improv(?:e|es|ing)|maintain(?:s|ing)?|refactor(?:s|ing)?|debug(?:s|ging)?)"
            rf"\b(?:\s+\w+){{0,3}}\s+{_BRAND}\b"
            # The brand named directly as the codebase/test-suite/source being
            # worked on -- a noun-phrase form independent of verb distance.
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
        # Fires on tenant isolation MANDATED as a rule for the customer's own
        # code/tests (Role 3). Deliberately does NOT fire on the platform
        # describing its own API ("tenant_key is auto-injected", "all queries
        # filter by tenant_key") — that is Role-1 self-description.
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
            # BE-9264 F5: \d{3,4} -> \d{3,} so a future 5-digit serial doesn't
            # silently fall out of the guard's coverage; ADR-/CHT- added
            # alongside the existing prefixes (architecture decisions and
            # Hub-thread chat ids are internal refs of the same kind).
            r"\b(?:BE|FE|INF|IMP|SEC|TSK|ADR|CHT)-\d{3,}[a-z]?\b"
            r"|\bHandover 0\d{2,3}[a-z]?\b"
            r"|\bIssue 0\d{3}(?:-\d)?\b"
        ),
        "Internal ticket/handover reference leaking into customer-rendered "
        "text. Customers cannot dereference these — delete the citation.",
        keep=(
            # The product's OWN taxonomy-alias format examples (Role 1 —
            # customers get BE-/TSK- style serials from the product itself).
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
            # Client-generic context-file guidance ("CLAUDE.md, AGENTS.md,
            # GEMINI.md, or your MCP client's equivalent") is Role 1.
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
        # alembic.ini is the role3_repo_file_rules pattern's hit, not a
        # stack example — the lookahead prevents a double-fire on that line.
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
            # Conditional/dual-OS shapes are GOOD platform handling:
            _p(r"(?i)if shell contains"),
            # bash/zsh are unambiguous POSIX-shell literals (never a bare
            # word used to falsely wave off a PowerShell-only mandate), so
            # they stay a plain keep. BE-9264 F3 narrows "linux"/"macos" to a
            # genuine section-HEADER shape: the label must sit at the start
            # of the line (optionally after a bullet/dash) or right after a
            # "|" alternative-separator, with its colon within 20 chars (a
            # short parenthetical annotation like "macOS (Terminal):" is
            # still allowed). A bare mention with an incidental downstream
            # colon no longer counts on its own -- audit finding (post-merge
            # review of this PR) showed the original `[^:]{0,20}:` proximity
            # check had NO position requirement, so it was fooled by any
            # nearby colon regardless of where the OS word sat in the
            # sentence: "Unlike Linux: you must always use PowerShell for
            # this step." has "Linux" immediately followed by ":" but is NOT
            # an alternative-offering header -- it still mandates PowerShell
            # only, and "Linux" is not at the start of the line. Requiring
            # the header POSITION (line start / bullet / post-pipe) is what
            # "Unlike Linux:" fails and "Linux/macOS:" / "- macOS (Terminal):"
            # continue to pass (the position anchor, not the char-count
            # bound, is what changed).
            # TSK-9267: the post-pipe anchor itself was still loose -- `\|\s*`
            # accepted a stray pipe ANYWHERE earlier in the line ("Use cmd |
            # Linux: to filter, but you must always use PowerShell ..."), so
            # a mid-sentence pipe falsely kept a PowerShell-only mandate. A
            # pipe now only anchors the label when it is a plausible
            # table/alternative separator: line-START table syntax (`^\s*\|`),
            # or a whitespace-preceded pipe that SEPARATES labeled cells (a
            # "Label:" segment precedes it -- `:[^|]*\s\|`), as in
            # "PowerShell: Get-Content -Wait x | Linux: tail -f x".
            _p(r"(?i)\bbash\b|\bzsh\b|(?:^\s*[-*]?\s*|^\s*\|\s*|:[^|]*\s\|\s*)(?:linux|macos)[^:]{0,20}:"),
            # Labeled-alternative conventions imply an adjacent non-Windows
            # branch (the per-OS launcher ladder / the dual-OS pair):
            _p(r"(?i)windows powershell:"),
            _p(r"(?i)- windows \(windows terminal\):"),
            _p(r"^\s*wt -w \d+ new-tab"),
        ),
        # A nearby bash/zsh mention, a labeled Linux/macOS HEADER (see the
        # keep-regex comment above for why the header position is required),
        # or an actual POSIX command literal within +/-3 lines of the same
        # template block marks a dual-shell pair split across wrapped lines
        # (e.g. "the Bash /\nPowerShell tool"). BE-9264 F3 (+ the post-merge
        # audit fix): bash/zsh stay unambiguous; the linux/macos cue now
        # requires the same header-position anchor as the same-line keep
        # (incl. the TSK-9267 tightened pipe branch -- the nearby window
        # contains the line itself, so a loose pipe here would undo the
        # same-line fix).
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
        # BE-9264 F2/gating fix: a genuinely `if tool == "claude-code":`-gated
        # multi-line block only carries the "Claude Code" label on its FIRST
        # (header) line — word-wrapped continuation lines below it fired
        # this pattern with no same-line "claude code" to keep them (e.g.
        # template_seeder.py's TOOLSEARCH BOOTSTRAP block: the label line
        # reads "...(Claude Code only...): In fresh Claude", so "Code
        # sessions, ..." on the NEXT line had nothing to keep it). A nearby
        # "claude code" within the window covers the whole gated block.
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


# ---------------------------------------------------------------------------
# Scanner


@dataclass(frozen=True)
class Hit:
    file: str  # repo-relative posix path
    line: int
    pattern_id: str
    text: str  # the matched line, stripped

    @property
    def fingerprint(self) -> str:
        norm = " ".join(self.text.split())
        raw = f"{self.file}|{self.pattern_id}|{norm}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _docstring_node_ids(tree: ast.Module) -> set[int]:
    """Identify module/class/function docstring nodes. In the scanned prompt
    modules the customer-rendered text lives in assigned template constants;
    docstrings are internal developer documentation and are NOT scanned
    (they would flood the guard with non-rendered ticket refs)."""
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
    """Yield (start_lineno, lines) for every non-docstring string constant
    in the module."""
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
    """Run the pattern engine over one rendered line. Returns pattern_ids
    that fire (keep-regexes, nearby-window and min-length gates applied).
    Unit-testable entry point for the keep-list and trip cases."""
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


# ---------------------------------------------------------------------------
# The guard


def test_no_new_dogfooding_contamination():
    """RED on any customer-reaching string that reintroduces dogfooding
    contamination and is not in the explicit baseline."""
    baseline_fps = {fp for fp, _note in BASELINE}
    new_hits = [h for h in scan_all() if h.fingerprint not in baseline_fps]
    assert not new_hits, format_report(new_hits)


def test_baseline_has_no_stale_entries():
    """RED when a baselined offender was cleaned but its entry not removed —
    the ratchet only turns one way, and the baseline must shrink with it."""
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
    """RED when the scanner has stopped looking at the repo.

    TSK-9314 emptied the baseline. That removed an ACCIDENTAL canary: while
    entries existed, a scanner that went blind made every baselined
    fingerprint unobserved and ``test_baseline_has_no_stale_entries`` went
    RED. With an empty baseline both guard tests above pass vacuously on a
    scanner that returns nothing — no baselined fingerprint to go stale, no
    hit to be new — so a SCAN_GLOB that silently stops matching (a package
    rename, an over-broad exclusion) would leave the guard reporting success
    while examining nothing. This is the deliberate replacement, and it is the
    only test that fails on that state.

    Deliberately loose floors: they catch a COLLAPSE, not normal churn. At the
    time of writing the surface is 67 files / ~6.9k scanned lines.
    """
    paths = resolve_scan_paths()
    assert len(paths) >= 50, (
        f"Neutrality guard scan surface collapsed to {len(paths)} files (expected >= 50). "
        "A glob has stopped matching or an exclusion is too broad — the guard is "
        "examining almost nothing and will pass vacuously."
    )

    # Per-glob, so one dead glob is caught even while the others still resolve.
    for pattern in SCAN_GLOBS:
        matched = [p for p in REPO_ROOT.glob(pattern) if p.name not in SCAN_EXCLUDE_NAMES]
        assert matched, f"SCAN_GLOB {pattern!r} matched no files — the scanned surface silently shrank."

    # An exclusion whose file no longer exists is a dead entry that will
    # silently start covering a NEW file if that name is ever reused.
    for name in SCAN_EXCLUDE_NAMES:
        assert any(REPO_ROOT.glob(f"**/{name}")), (
            f"SCAN_EXCLUDE_NAMES entry {name!r} matches no file in the repo — remove the stale exclusion."
        )

    # Resolving paths is not the same as reading prose out of them: this fails
    # if the files are reachable but the AST walk yields nothing.
    scanned_lines = 0
    for path in paths:
        for _start, lines in iter_string_constants(path.read_text(encoding="utf-8")):
            scanned_lines += sum(1 for ln in lines if ln.strip())
    assert scanned_lines >= 3000, (
        f"Only {scanned_lines} string-constant lines scanned (expected >= 3000). "
        "The scanner resolves files but is not extracting prose from them."
    )


def test_guard_catches_a_planted_violation_end_to_end(tmp_path, monkeypatch):
    """The whole chain — resolve_scan_paths -> scan_file -> fingerprint — on a
    planted offender.

    The other self-tests exercise ``match_prose_line`` on synthetic strings
    (pattern engine) or ``iter_string_constants`` on a temp file (parser).
    Neither proves the GLOB MACHINERY still delivers real files to the
    matcher, which is precisely what an empty baseline stops noticing. This
    plants contamination in a miniature repo laid out like the real one and
    asserts the guard surfaces it with a usable fingerprint.
    """
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


# ---------------------------------------------------------------------------
# Keep-list unit cases — Role-1 branding and conditional platform handling
# must NEVER trip the guard. If a pattern change breaks one of these, the
# pattern is over-reaching.

KEEP_CASES = [
    "You are the Orchestrator Agent for Giljo HQ.",
    "You are an agent powered by Giljo HQ coordinating this project.",
    "This message comes from an agent from Giljo HQ.",
    # BE-9361: the pre-rename brand must stay Role-1-safe too -- un-migrated
    # template rows and older prose still say "GiljoAI MCP".
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
    # BE-9264 F1 advisory (post-merge audit on PR #589): GiljoAI as the
    # SUBJECT helping the customer test THEIR OWN codebase must stay
    # Role-1-safe -- it is not GiljoAI named as the target/software-under-test.
    "GiljoAI helps agents test the customer's codebase.",
    # TSK-9267 locks for the two legitimate pipe shapes the tightened keep
    # must still accept: a line-start table row, and a whitespace-preceded
    # pipe separating two LABELED cells.
    "| Linux: use gnome-terminal | Windows: use Windows Terminal |",
    "PowerShell: Get-Content -Wait log.txt | Linux: tail -f log.txt",
]


@pytest.mark.parametrize("text", KEEP_CASES)
def test_keep_list_never_trips(text: str):
    assert match_prose_line(text) == [], f"Keep-list text wrongly flagged: {text!r}"


# ---------------------------------------------------------------------------
# Trip cases — synthetic contamination MUST fire. If a pattern change breaks
# one of these, the guard has gone blind to that category.

TRIP_CASES = [
    ("Testing specialist for Giljo HQ with strict TDD.", "role2_target_product"),
    ("The software you are improving is Giljo HQ.", "role2_target_product"),
    # BE-9264 F1 probes: verb-based Role-2 forms the old pattern missed
    # (specialist/tester/reviewer/... "for GiljoAI" was too narrow a shape).
    ("Write comprehensive tests for Giljo HQ.", "role2_target_product"),
    ("You are improving the Giljo HQ codebase.", "role2_target_product"),
    ("The GiljoAI codebase you are testing has strict conventions.", "role2_target_product"),
    ("Please maintain Giljo HQ's test suite going forward.", "role2_target_product"),
    # BE-9361: the same Role-2 shapes under the PRE-rename brand must still
    # fire -- the rename must not quietly narrow the guard to one name.
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
    # BE-9264 F3 probes: a bare "Linux"/"macOS" mention used to falsely KEEP
    # the hit even though PowerShell was asserted as mandatory, not offered
    # as one of a labeled pair.
    ("Unlike Linux, you must always use PowerShell for this step.", "os_shell_literal"),
    ("Even on macOS you must always launch PowerShell for this step.", "os_shell_literal"),
    # Post-merge audit finding on PR #589: a colon (instead of the comma
    # above) right after "Linux" satisfied the old `[^:]{0,20}:` proximity
    # keep even though the sentence still mandates PowerShell only -- the
    # keep must require the label to sit at a genuine header POSITION, not
    # merely have a colon somewhere nearby.
    ("Unlike Linux: you must always use PowerShell for this step.", "os_shell_literal"),
    # TSK-9267: the pipe branch of the keep-regex anchored only on "| Linux:"
    # appearing ANYWHERE, so a stray mid-sentence pipe ahead of an OS label
    # falsely kept a PowerShell-only mandate. A pipe only marks a genuine
    # alternative/table separator when the line IS table syntax (starts with
    # "|") or the pipe separates two LABELED cells (a "Label:" segment
    # precedes it). This probe has neither — it must fire.
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
    # A short dict-key-style literal must not fire the prose-only tenant rule.
    assert match_prose_line("tenant_key", string_len=10) == []
    # The same words inside a long prose template must fire.
    long_line = "- Every test involving DB queries must verify `tenant_key` filtering."
    assert "role3_tenant_rule" in match_prose_line(long_line, string_len=500)


def test_synthetic_injection_detected(tmp_path: Path):
    """End-to-end self-test: a file containing Role-2 + OS + git-host
    contamination is detected by the scanner (guards the scanner itself
    against silently going blind)."""
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
