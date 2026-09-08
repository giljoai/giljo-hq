# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9564 -- the dashboard's copy-prompts may only name tools the server answers to.

The UI never executes anything: its copy-prompt buttons hand a user text that
the user pastes into their own agent (ruling 19 makes those buttons permanent).
So a retired tool name in frontend prompt text is not a stale comment -- it is
an instruction to a real user's agent to call something that no longer exists.
BE-9554 renamed nine tools and four such sites shipped to production.

THE SERVER-SIDE HALF OF THIS GUARD IS BE-9563. The two must never disagree
about which names are dead, so they share ONE map -- ``RETIRED_TOOL_NAMES`` in
``tests/helpers/retired_tool_names.py`` -- and that map is itself validated
against the live registry by BE-9563's ``test_every_key_is_actually_retired``.
Do not copy the map here. A second list is the defect both projects exist to fix.

WHY THIS IS A PYTHON TEST SCANNING FRONTEND FILES, and not a vitest spec: the
authority for "which tools ship" is ``TOOL_SCOPES``, a Python dict. A vitest
guard cannot read it, so it would need the roster exported to JavaScript -- and
a generated roster is a second list that drifts exactly the way the two guards
above were about to. Precedent for a Python test owning a frontend-facing
contract: ``tests/test_fe9200_tutorial_prompt_contract.py``.

TWO LAYERS, because each catches what the other cannot:

* ``test_no_frontend_source_names_a_retired_tool`` (layer A) reads the shared
  map and scans every frontend source, ``.spec.js`` included. It catches a dead
  name in a bare comment, where there is no call syntax to key on -- and it
  catches it in a spec, which is where a dead name goes to be pinned in place.
* ``test_every_claimed_tool_reference_is_registered`` (layer B) is the positive
  check: it goes the other way, extracting text that CLAIMS to name a tool and
  requiring the name to be in ``TOOL_SCOPES``. It needs no list, so it catches a
  retired name nobody remembered to write down.

WHY LAYER B'S DETECTOR IS SHAPED THE WAY IT IS. Layer B matches a small set of
shapes that indicate hand-written prompt text naming a tool. The obvious broad
scan -- any snake_case token followed by ``(`` -- was measured and produced far
too many false positives on this tree, almost all of them parameter names and
ordinary JS helpers; do not rebuild it.

If layer B fires on something that is genuinely not a tool reference, widen the
shape -- do not add the name to an allowlist. An allowlist here would turn the
guard into the thing it exists to prevent.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from api.endpoints.mcp_tools._base import TOOL_SCOPES
from tests.helpers.retired_tool_names import RETIRED_TOOL_NAMES


REPO_ROOT = Path(__file__).resolve().parents[2]

# BOTH trees. ``frontend/tests`` is not an afterthought: when this guard was
# written, ``frontend/tests/unit/views/RoadmapView.spec.js`` was asserting that
# the copy-prompt CONTAINS ``update_roadmap_metadata`` -- a test actively
# holding the dead name in place, and invisible to a scan of ``src`` alone.
FRONTEND_ROOTS = (REPO_ROOT / "frontend" / "src", REPO_ROOT / "frontend" / "tests")

_SOURCE_SUFFIXES = (".vue", ".js", ".ts")

# A Giljo tool name: snake_case, at least one underscore. The lookbehind is
# load-bearing -- see _QUALIFIED below.
_NAME = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+"

# A name reached through a module or service is NOT the MCP tool of that name,
# and the codebase already writes it that way at ~50 sites
# (``comm_thread.post``, ``taxonomy.validate``). Three live symbols in the
# frontend's comments share a name with something retired at the tool layer:
# ``comm_threads.search_threads`` (a live REST handler, while the TOOL is now
# ``list_threads(query=)``), ``mission_service.get_agent_mission`` (a live
# service method, while the TOOL is ``get_job_mission``), and
# ``vision_analysis.update_product_fields``. Flagging those would push the next
# author toward an allowlist, which is how a denylist dies. Requiring the dot
# instead keeps the sentence honest.
_QUALIFIED = r"(?<![\w.])"

# Stripped before matching so `<code>save_roadmap</code>` and `save_roadmap`
# are the same text to the detector. RoadmapView renders one and copies the
# other, and both were wrong.
_MARKUP = re.compile(r"</?code>|`")

# The four shapes that mean "this text is naming a tool to call". See the
# module docstring for why an ordinary `name(` scan is not among them.
_CLAIM_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # An explicit MCP-prefixed tool token, as a user's client displays it.
    ("mcp-prefix", re.compile(r"mcp__giljo_(?:hq|mcp)__(" + _NAME + r")")),
    # `get_vision_document(product_id="...")` -- keyword-argument call syntax,
    # which JavaScript does not have. This is the high-signal shape.
    ("kwarg-call", re.compile(_QUALIFIED + r"(" + _NAME + r")\(\s*[a-z_]+\s*=")),
    # "Call get_roadmap first", "by calling save_roadmap with"
    (
        "call-verb",
        re.compile(r"\b(?:call|calling|invoke|invoking)\s+(?:the\s+)?" + _QUALIFIED + r"(" + _NAME + r")\b", re.I),
    ),
    # "the save_roadmap MCP tool"
    ("mcp-tool-phrase", re.compile(_QUALIFIED + r"(" + _NAME + r")\s+MCP tool\b")),
)


def _frontend_sources() -> list[Path]:
    """Every frontend source file, specs included.

    Specs are IN scope deliberately: four of them were pinning
    ``get_vision_doc(product_id=...)`` in place when this guard was written, so
    excluding them would have hidden a third of the defect.
    """
    return sorted(
        p
        for root in FRONTEND_ROOTS
        for p in root.rglob("*")
        if p.suffix in _SOURCE_SUFFIXES and "node_modules" not in p.parts and p.is_file()
    )


def _scan(pattern: re.Pattern[str]) -> list[tuple[str, int, str, str]]:
    """Yield (relative path, line number, matched name, source line)."""
    found: list[tuple[str, int, str, str]] = []
    for path in _frontend_sources():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for match in pattern.finditer(_MARKUP.sub("", raw)):
                found.append((rel, lineno, match.group(1), raw.strip()))
    return found


def test_frontend_source_tree_is_where_this_test_thinks_it_is() -> None:
    """A scan over an empty file list passes vacuously -- this is what stops that.

    Both layers below report "no hits" if ``frontend/src`` ever moves. Assert
    the tree is present and populated so a silent pass is impossible.
    """
    for root in FRONTEND_ROOTS:
        assert root.is_dir(), f"frontend source tree missing at {root}"
    sources = _frontend_sources()
    assert len(sources) > 100, f"only {len(sources)} frontend sources found -- the scan root is wrong"


def test_no_frontend_source_names_a_retired_tool() -> None:
    """Layer A -- no retired tool name anywhere in the frontend, comments included.

    Reads the SHARED map, so this guard and BE-9563's cannot disagree about
    which names are dead.
    """
    retired = re.compile(_QUALIFIED + r"(" + "|".join(re.escape(n) for n in sorted(RETIRED_TOOL_NAMES)) + r")\b")
    hits = _scan(retired)
    assert not hits, "frontend sources naming a retired MCP tool:\n" + "\n".join(
        f"  {rel}:{lineno}  {name} -> {RETIRED_TOOL_NAMES[name]}\n      {line[:120]}"
        for rel, lineno, name, line in hits
    )


def test_every_claimed_tool_reference_is_registered() -> None:
    """Layer B -- text that claims to name a tool must name a REGISTERED one.

    Needs no list of dead names, so it catches a rename nobody wrote down.
    """
    unknown: list[str] = []
    for label, pattern in _CLAIM_SHAPES:
        for rel, lineno, name, line in _scan(pattern):
            if name not in TOOL_SCOPES:
                replacement = RETIRED_TOOL_NAMES.get(name, "not a registered tool")
                unknown.append(f"  {rel}:{lineno}  [{label}] {name} -> {replacement}\n      {line[:120]}")
    assert not unknown, "frontend text names tools that are not in the shipped registry:\n" + "\n".join(
        sorted(set(unknown))
    )


def test_the_shipped_names_carry_the_arguments_the_rename_moved() -> None:
    """A rename that moved an argument is only half-applied if the name alone is carried.

    ``await_my_turn(agent_id)`` became ``get_my_turn(agent_id, wait_seconds=45)``:
    without ``wait_seconds`` the call answers instantly, so a prompt that carries
    the name and drops the argument tells a user's agent to park on something
    that does not park. BE-9554's own sweep shipped that defect six times, which
    is why it is asserted rather than trusted.
    """
    required_arguments = {
        "get_my_turn": "wait_seconds",
        "list_threads": "query",
    }
    offenders: list[str] = []
    call = re.compile(_QUALIFIED + r"(" + _NAME + r")\((?P<args>[^)]*)\)")
    for path in _frontend_sources():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            line = _MARKUP.sub("", raw)
            for match in call.finditer(line):
                argument = required_arguments.get(match.group(1))
                # Only prompt text is judged: a bare `get_my_turn()` in JS is a
                # local helper, while `get_my_turn(agent_id=...)` is an
                # instruction. The kwarg is what makes it the latter.
                if argument and "=" in match.group("args") and argument not in match.group("args"):
                    offenders.append(
                        f"  {rel}:{lineno}  {match.group(1)}(...) is missing {argument}=\n      {raw.strip()[:120]}"
                    )
    assert not offenders, "prompt text carries a renamed tool but dropped the argument the rename moved:\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize(
    ("shape", "sample"),
    [
        ("mcp-prefix", "  // see mcp__giljo_hq__update_roadmap_metadata for the write path"),
        ("kwarg-call", '  `1. Call get_vision_doc(product_id="${id}") and follow it`,'),
        ("call-verb", "  '5. Save by calling update_roadmap_metadata with',"),
        ("mcp-tool-phrase", "  (it writes the roadmap via the <code>update_roadmap_metadata</code> MCP tool)"),
    ],
)
def test_each_claim_shape_actually_fires(shape: str, sample: str) -> None:
    """Each detector shape must fire on the line it was written for.

    Without this, a regex that silently stops matching turns layer B into a test
    that passes because it sees nothing -- the exact way BE-9554's
    cross-reference guard went inert for a release.
    """
    pattern = dict(_CLAIM_SHAPES)[shape]
    match = pattern.search(_MARKUP.sub("", sample))
    assert match, f"shape {shape!r} no longer fires on the text it was written for: {sample!r}"
    assert match.group(1) not in TOOL_SCOPES


def test_claim_shapes_ignore_ordinary_javascript() -> None:
    """The detector must not fire on plain JS, or it gets an allowlist and dies.

    ``activeProduct.value?.name`` and ``buildRoadmapPrompt(mode)`` are not tool
    references; a scan that flags them acquires exceptions until it means nothing.
    """
    benign = [
        "  const ok = await copy(promptText.value)",
        "  function buildRoadmapPrompt(mode) {",
        "  emit_websocket_event(payload)",
        "  const { product_id, project_id } = route.params",
        "  await api.prompts.implementation(projectId)",
    ]
    for line in benign:
        for shape, pattern in _CLAIM_SHAPES:
            assert not pattern.search(_MARKUP.sub("", line)), f"shape {shape!r} false-fired on ordinary JS: {line!r}"


def test_module_qualification_exempts_a_symbol_but_a_bare_name_still_fires() -> None:
    """The dot is the whole exemption -- prove it narrows and does not blanket.

    ``comm_threads.search_threads`` is a live REST handler and must pass;
    ``search_threads(run_id)`` in a sentence about what an agent does is the
    retired tool and must fail. If this test ever passes with the second line
    exempted, the exemption has widened into an allowlist.
    """
    retired = re.compile(_QUALIFIED + r"(" + "|".join(re.escape(n) for n in sorted(RETIRED_TOOL_NAMES)) + r")\b")
    exempt = "  // the backend /threads/search endpoint (comm_threads.search_threads)"
    caught = "  * finds it the SAME way every sub-orchestrator does: search_threads(run_id)."
    assert not retired.search(exempt), "module-qualified live symbol must not be flagged"
    assert retired.search(caught), "a bare retired tool name must still be flagged"
