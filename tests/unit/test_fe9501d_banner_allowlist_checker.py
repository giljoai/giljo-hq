# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import ast
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKGROUND_TASKS = REPO_ROOT / "api" / "startup" / "background_tasks.py"
_CONTEXT_TUNING_BANNER = REPO_ROOT / "api" / "startup" / "context_tuning_banner.py"
_SYSTEM_STATUS_BANNER_VUE = REPO_ROOT / "frontend" / "src" / "components" / "system" / "SystemStatusBanner.vue"

_BOTH_EDITION_TYPES = {"system.skills_drift", "system.context_tuning_due"}

_BANNER_SURFACES = {"banner", "both"}


def _emitted_system_banner_types(path: Path) -> set[str]:
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
    match = re.search(rf"{re.escape(var_name)}\s*(?:=\s*)?new Set\(\[(.*?)\]\)", text, re.DOTALL)
    assert match, (
        f"could not find `{var_name} ... new Set([...])` in SystemStatusBanner.vue -- "
        "this checker is stale against a refactor and needs updating, not deleting"
    )
    body = match.group(1)
    body = re.sub(r"//.*", "", body)
    return set(re.findall(r"'([\w.]+)'", body))


def _ce_system_types() -> set[str]:
    text = _SYSTEM_STATUS_BANNER_VUE.read_text()
    return _parse_js_string_set(text, "CE_SYSTEM_TYPES")


def _saas_allowed_types() -> set[str]:
    text = _SYSTEM_STATUS_BANNER_VUE.read_text()
    block_match = re.search(r"const ALLOWED_TYPES = computed\(.*?\n\}\)", text, re.DOTALL)
    assert block_match, "could not find the ALLOWED_TYPES computed block in SystemStatusBanner.vue"
    return _parse_js_string_set(block_match.group(0), "return")


def test_ce_emitted_system_banner_types_are_all_in_ce_allowlist():
    emitted = _emitted_system_banner_types(_BACKGROUND_TASKS) | _emitted_system_banner_types(_CONTEXT_TUNING_BANNER)
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
    saas_types = _saas_allowed_types()
    missing = _BOTH_EDITION_TYPES - saas_types
    assert not missing, (
        f"system.* type(s) {sorted(missing)} are emitted regardless of edition "
        "but missing from ALLOWED_TYPES's SaaS branch in SystemStatusBanner.vue "
        "-- they will render in CE and be invisible in SaaS."
    )
