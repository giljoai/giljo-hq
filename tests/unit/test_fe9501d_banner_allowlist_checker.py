# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Headless S3d (D17) durable guard: a backend-emitted `system.*` banner type
missing from SystemStatusBanner.vue's allowlist must FAIL A TEST, not render
nowhere.

Proven live before this project: ``system.tool_rename_notice`` was emitted at
``background_tasks.py:319`` with ``surface="banner"`` and never appeared in
``CE_SYSTEM_TYPES`` -- the row existed in the ``notifications`` table and had
no path to the screen. This test statically discovers every `system.*` type
the CE emitter modules push with a banner-eligible surface and asserts the
Vue component's allowlist(s) recognize it, so the NEXT such omission fails
here instead of shipping invisible.

Static (AST + regex) by design: this must catch the gap at review/CI time,
before a human ever looks at the running app and notices nothing is there.
"""

import ast
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKGROUND_TASKS = REPO_ROOT / "api" / "startup" / "background_tasks.py"
_CONTEXT_TUNING_BANNER = REPO_ROOT / "api" / "startup" / "context_tuning_banner.py"
_SYSTEM_STATUS_BANNER_VUE = REPO_ROOT / "frontend" / "src" / "components" / "system" / "SystemStatusBanner.vue"

# The two `system.*` types emitted UNCONDITIONALLY inside
# background_tasks.emit_system_banners (outside its `if not is_saas:` guard --
# see the comment there: "Emits in BOTH editions"). The other three CE types
# (pending_migrations, update_available, tool_rename_notice) are CE-only by
# that same guard and therefore need no SaaS-allowlist entry.
_BOTH_EDITION_TYPES = {"system.skills_drift", "system.context_tuning_due"}

_BANNER_SURFACES = {"banner", "both"}


def _emitted_system_banner_types(path: Path) -> set[str]:
    """AST-scan one module for every `notification_type="system.*"` keyword
    argument co-occurring with `surface="banner"` / `surface="both"` on the
    same call (a NotificationService.create/upsert_by_dedupe_key invocation).

    Walks the whole module, not just a named function, so it survives the
    per-type emission being split into helper functions (as it is today:
    `_emit_pending_migrations_banner`, `_emit_tool_rename_notice_banner`, ...).
    """
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
        type_node = kwargs.get("notification_type")
        surface_node = kwargs.get("surface")
        if not (isinstance(type_node, ast.Constant) and isinstance(type_node.value, str)):
            continue
        if not type_node.value.startswith("system."):
            continue
        if not (isinstance(surface_node, ast.Constant) and surface_node.value in _BANNER_SURFACES):
            continue
        found.add(type_node.value)
    return found


def _parse_js_string_set(text: str, var_name: str) -> set[str]:
    """Extract the string literals inside `{var_name} = new Set([...])`.

    Regex, not a JS parser -- deliberate and sufficient: this only ever reads
    a `new Set([...])` literal of quoted strings, the exact shape both
    CE_SYSTEM_TYPES and ALLOWED_TYPES's SaaS branch use.
    """
    # `(?:=\s*)?` because the SaaS branch is a bare `return new Set([...])`
    # (no `=`) while CE_SYSTEM_TYPES is `const CE_SYSTEM_TYPES = new Set([...])`.
    match = re.search(rf"{re.escape(var_name)}\s*(?:=\s*)?new Set\(\[(.*?)\]\)", text, re.DOTALL)
    assert match, (
        f"could not find `{var_name} ... new Set([...])` in SystemStatusBanner.vue -- "
        "this checker is stale against a refactor and needs updating, not deleting"
    )
    body = match.group(1)
    # Strip `//` line comments first -- an apostrophe inside a comment (e.g.
    # "background_tasks.py's") would otherwise open a bogus quoted span that
    # swallows real entries into one malformed match.
    body = re.sub(r"//.*", "", body)
    return set(re.findall(r"'([\w.]+)'", body))


def _ce_system_types() -> set[str]:
    text = _SYSTEM_STATUS_BANNER_VUE.read_text()
    return _parse_js_string_set(text, "CE_SYSTEM_TYPES")


def _saas_allowed_types() -> set[str]:
    """The SaaS branch of `ALLOWED_TYPES` (the first `new Set([...])` inside
    the `computed(() => { if (isSaasModeValue(...)) { ... } ...})` block)."""
    text = _SYSTEM_STATUS_BANNER_VUE.read_text()
    block_match = re.search(r"const ALLOWED_TYPES = computed\(.*?\n\}\)", text, re.DOTALL)
    assert block_match, "could not find the ALLOWED_TYPES computed block in SystemStatusBanner.vue"
    return _parse_js_string_set(block_match.group(0), "return")


def test_ce_emitted_system_banner_types_are_all_in_ce_allowlist():
    """Every `system.*` type the CE emitter modules push with a banner-eligible
    surface must be in CE_SYSTEM_TYPES -- CE mode can emit any of them (the
    `is_saas` guard only suppresses a subset under SaaS; under CE every one of
    these call sites is live), so a gap here is a row that lands in the DB and
    renders nowhere -- exactly the tool_rename_notice bug this project fixed.
    """
    emitted = _emitted_system_banner_types(_BACKGROUND_TASKS) | _emitted_system_banner_types(_CONTEXT_TUNING_BANNER)
    # Sanity: the scan itself must find something, or this test is vacuously
    # green and proves nothing (empty-result-is-not-clean).
    assert emitted, "AST scan found zero system.* banner emitters -- the checker itself is broken"

    ce_types = _ce_system_types()
    missing = emitted - ce_types
    assert not missing, (
        f"backend emits system.* banner type(s) {sorted(missing)} with "
        "surface banner/both, but SystemStatusBanner.vue's CE_SYSTEM_TYPES "
        "does not include them -- the notification row will be created and "
        "never render (D17's exact failure mode). Add the type to "
        "CE_SYSTEM_TYPES in frontend/src/components/system/SystemStatusBanner.vue."
    )


def test_both_edition_system_banner_types_are_also_in_saas_allowlist():
    """The two types emitted unconditionally (both editions) must also render
    under SaaS -- CE_SYSTEM_TYPES alone is not read there."""
    saas_types = _saas_allowed_types()
    missing = _BOTH_EDITION_TYPES - saas_types
    assert not missing, (
        f"system.* type(s) {sorted(missing)} are emitted regardless of edition "
        "but missing from ALLOWED_TYPES's SaaS branch in SystemStatusBanner.vue "
        "-- they will render in CE and be invisible in SaaS."
    )
