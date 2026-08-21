# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Roadmap input-validation boundary (extracted from RoadmapService, IMP-6044).

Pure, DB-free validation for the Roadmapping Pane write tools. These functions
run BEFORE any DB write so a malformed agent payload raises ValidationError
(→ 422) at the boundary rather than tripping a DB constraint as a 500 — the
"no unvalidated agent input → DB" discipline (mirrors jsonb_validators.py).

No session, no tenant, no I/O: every function is a deterministic transform from
raw payload to a normalized list (or raises). Kept separate from RoadmapService
so the validation contract is independently testable and the service stays
focused on DB orchestration.

BE-9474 — EVERY blocker in one round trip. An agent using this tool ranked seventeen
items, one of them carrying a 580-character ``blocked_reason``, and learned about
exactly that one row; every later problem cost another full resend. The checks
below now COLLECT failures and raise once, carrying the primary failure in the
message head (unchanged wording, so a single-fault rejection reads exactly as it
always did) and every other failure appended after ``||`` plus a structured
``all_failures`` list in the context. Shape copied deliberately from
``memory_entry_write_validator.MemoryEntryWriteValidationError`` rather than
invented: BE-8003b established that the MCP boundary surfaces ``str(exc)``, so a
structured key that is not also rendered into the message never reaches the
agent at all.

BE-9477 — WHICH KEYS THE PAYLOAD ACTUALLY CARRIED. Normalization defaults every
omission (``sort_order``->0, ``risk``/``complexity``->NULL, ``blocked``->False), which
is correct for a full write and destroys the one distinction ``patch_fields``
rests on: an OMITTED key means "keep what is stored", an explicitly EMPTY one
means "clear it". Nothing downstream can recover that from the normalized row —
both look like the default. So under the flag each row also records the set of
metadata keys it literally supplied, in ``_patch_fields``. That is what makes
``coalesce(excluded.x, table.x)`` unnecessary as well as insufficient: absent
and null are decided HERE, at the boundary, not guessed at in SQL.

Two things this deliberately does NOT do:

- **No soft-truncate.** Silently storing 500 of an agent's 580 characters would
  make a successful write a lie — the agent believes it saved a note it can
  read back, and cannot. The tolerate-the-old-shape rule in CODE_STANDARDS is
  about rows already in the database, not about quietly discarding new input,
  and there is no warning channel on this tool an agent reliably reads. The
  pain that run actually reported was the sixteen GOOD rows dying,
  which batching fixes; nobody asked to have their text mangled to fit.
- **No partial application.** The batch stays atomic. A half-applied re-rank
  leaves a roadmap in an order no one chose, which is worse than a rejected one.

Edition Scope: CE.
"""

from typing import Any, NoReturn

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.roadmaps import (
    MAX_BLOCKED_REASON_LEN,
    MAX_ROADMAP_SORT_ORDER,
    VALID_ROADMAP_COMPLEXITIES,
    VALID_ROADMAP_ITEM_TYPES,
    VALID_ROADMAP_RISKS,
)


# The metadata columns a roadmap item may carry, in the order
# ``roadmap_upsert.upsert_many`` writes them. Canonical order matters: the
# ``ON CONFLICT DO UPDATE`` set is built from this tuple, so with the flag off
# the emitted statement is exactly the one emitted before BE-9477 existed.
PATCHABLE_ITEM_FIELDS: tuple[str, ...] = (
    "sort_order",
    "risk",
    "complexity",
    "blocked",
    "blocked_reason",
)

# Key carrying the frozenset of metadata columns an item LITERALLY supplied.
# Present on a normalized item ONLY under ``patch_fields`` (BE-9477). It cannot
# be added unconditionally: the normalized dict is a shipped contract asserted
# by whole-dict equality, so an always-on extra key would change what every
# existing caller sees for no reason. Flag off -> byte-identical dict.
PATCH_FIELDS_KEY: str = "_patch_fields"


# Length ceiling for an agent-supplied project/task reference. ``items`` is
# typed ``list[dict[str, Any]]`` at the MCP boundary, so FastMCP applies no
# per-value cap the way it does to a declared ``str`` parameter — the cap has to
# live here (no unvalidated agent input → DB). Sized to match ``MCP_ID_MAX``,
# which bounds the same identifiers where they ARE declared parameters. A value
# over the cap is refused today too, as an id that matches nothing; this only
# replaces a misleading "does not exist" with the real reason.
MAX_ROADMAP_REF_LEN: int = 64


def format_missing_refusal(
    *,
    noun: str,
    elsewhere: list[str],
    unknown: list[str],
    active_label: str,
) -> str:
    """Word the roadmap's item-rejection so it is TRUE, not merely loud (BE-9420).

    Both rejection reasons used to render as "not found in the active product".
    After a product flip -- an ordinary user action -- the common case is an id
    that exists perfectly well one product over, so the user was told their
    project was missing when it was not. A correct boundary reading as a bug is
    how the refusal became a nuisance.

    Pure and DB-free, like everything else in this module: the caller does the
    tenant-scoped lookups that decide which id lands in which bucket, and this
    only decides how to say it. That split is what keeps the sentence testable
    without a database.
    """
    parts: list[str] = []
    if elsewhere:
        parts.append(
            f"{noun}(s) {sorted(elsewhere)} belong to a different product, not the active product "
            f"{active_label} -- a roadmap only holds items of its own product, so activate theirs "
            f"or leave them off this one"
        )
    if unknown:
        parts.append(f"{noun}(s) {sorted(unknown)} do not exist in this workspace")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Batched rejection (BE-9474)
# ---------------------------------------------------------------------------


def _fail(field: str, message: str, **extra: Any) -> dict[str, Any]:
    """One collected blocker. ``extra`` keys are the legacy per-failure context
    keys (``valid_risks``, ``max_sort_order``, …) and are preserved verbatim so
    a single-failure rejection carries exactly the context it carried before."""
    return {"field": field, "message": message, **extra}


def raise_roadmap_failures(failures: list[dict[str, Any]], *, operation: str) -> NoReturn:
    """Raise ONE ValidationError describing every collected blocker.

    Single failure → byte-identical to the pre-BE-9474 rejection (same message,
    same context keys). Multiple → the primary still leads, each further blocker
    is appended to the message after ``||`` (BE-8003b: the MCP boundary renders
    ``str(exc)``, so anything only in the context is invisible to the agent), and
    the full list is attached as ``all_failures`` for programmatic readers such
    as the REST error serializer.
    """
    primary = failures[0]
    message = primary["message"]
    if len(failures) > 1:
        message = " || ".join([message] + [f"ALSO FAILED: {f['message']}" for f in failures[1:]])

    context: dict[str, Any] = {"operation": operation}
    context.update({k: v for k, v in primary.items() if k not in ("field", "message")})
    if len(failures) > 1:
        context["all_failures"] = failures
    raise ValidationError(message=message, context=context)


# ---------------------------------------------------------------------------
# Per-field checks -- collecting form (``_check_*``) + raising form (public)
# ---------------------------------------------------------------------------


def _check_sort_order(value: Any, idx: int) -> tuple[int, list[dict[str, Any]]]:
    field = f"items[{idx}].sort_order"
    if isinstance(value, bool) or not isinstance(value, int):
        return 0, [_fail(field, f"{field} must be an integer")]
    if value < 0 or value > MAX_ROADMAP_SORT_ORDER:
        return 0, [
            _fail(
                field,
                f"{field} must be between 0 and {MAX_ROADMAP_SORT_ORDER}",
                max_sort_order=MAX_ROADMAP_SORT_ORDER,
            )
        ]
    return value, []


def validate_sort_order(value: Any, idx: int) -> int:
    sort_order, failures = _check_sort_order(value, idx)
    if failures:
        raise_roadmap_failures(failures, operation="upsert_roadmap_items")
    return sort_order


def _check_blocked(blocked: Any, blocked_reason: Any, idx: int) -> tuple[bool, str | None, list[dict[str, Any]]]:
    """Validate the agent-flagged dependency block (FE-6022d): ``blocked`` is a
    real bool (default False); ``blocked_reason`` is optional free-text capped
    at ``MAX_BLOCKED_REASON_LEN`` and dropped when not blocked (no stale notes).

    Both fields are checked even when the first fails, so an item with a
    non-bool ``blocked`` AND an over-long reason reports both (BE-9474).
    """
    failures: list[dict[str, Any]] = []

    if blocked is None:
        blocked_bool = False
    elif isinstance(blocked, bool):
        blocked_bool = blocked
    else:
        blocked_bool = False
        failures.append(_fail(f"items[{idx}].blocked", f"items[{idx}].blocked must be a boolean"))

    reason = blocked_reason if blocked_reason not in (None, "") else None
    if reason is not None and not isinstance(reason, str):
        failures.append(_fail(f"items[{idx}].blocked_reason", f"items[{idx}].blocked_reason must be a string"))
        reason = None
    reason = reason.strip() or None if reason is not None else None
    if reason is not None and len(reason) > MAX_BLOCKED_REASON_LEN:
        failures.append(
            _fail(
                f"items[{idx}].blocked_reason",
                f"items[{idx}].blocked_reason exceeds {MAX_BLOCKED_REASON_LEN} characters (got {len(reason)})",
                max_blocked_reason_len=MAX_BLOCKED_REASON_LEN,
                actual_len=len(reason),
            )
        )
        reason = None

    # An unblocked item carries no reason.
    return blocked_bool, (reason if blocked_bool else None), failures


def validate_blocked(blocked: Any, blocked_reason: Any, idx: int) -> tuple[bool, str | None]:
    blocked_bool, reason, failures = _check_blocked(blocked, blocked_reason, idx)
    if failures:
        raise_roadmap_failures(failures, operation="upsert_roadmap_items")
    return blocked_bool, reason


def _check_ref(value: Any, field: str) -> list[dict[str, Any]]:
    """Length gate on an agent-supplied project/task reference.

    ``items``/``remove`` arrive as untyped dicts, so this is the only place a
    10-kilobyte "project_id" is stopped before it becomes an ``IN`` predicate.

    Deliberately NOT a type gate: a numeric id is coerced with ``str()`` here as
    it always has been (``validate_items([{... "project_id": 123 ...}])`` is a
    shipped, tested contract), so the cap is measured on the coerced form. A
    value over the cap is rejected today too — as an id matching no row — so
    this changes the sentence the agent reads, never whether the call succeeds.
    """
    coerced = str(value)
    if len(coerced) > MAX_ROADMAP_REF_LEN:
        return [
            _fail(
                field,
                f"{field} exceeds {MAX_ROADMAP_REF_LEN} characters (got {len(coerced)})",
                max_ref_len=MAX_ROADMAP_REF_LEN,
                actual_len=len(coerced),
            )
        ]
    return []


# ---------------------------------------------------------------------------
# items
# ---------------------------------------------------------------------------


def _check_patch_pairing(raw: dict[str, Any], idx: int) -> list[dict[str, Any]]:
    """``blocked`` and ``blocked_reason`` patch together, or not at all (BE-9477).

    The two are not independent columns: an unblocked item carries no reason,
    the invariant :func:`_check_blocked` has always enforced. Honouring it with
    only one of the pair present would need the row's STORED state, which this
    module deliberately cannot see.

    **THE RULE IS DELIBERATELY OVER-BROAD, AND THE REASON IS DECIDABILITY, NOT
    DAMAGE.** Do not "fix" it by permitting the safe case -- read this first.
    Under patch semantics an unmentioned column is simply absent from the
    ``SET`` clause, so the stored value survives, and that makes each single-key
    case land differently:

    - ``{blocked: true}`` alone is ALWAYS SAFE. The stored reason survives, and
      a blocked row carrying a reason satisfies the invariant. This rule refuses
      it anyway.
    - ``{blocked: false}`` alone strands the stored note on an unblocked row --
      but only when a reason was actually stored.
    - ``{blocked_reason: "x"}`` alone keeps the stored ``blocked``. Fine over a
      stored ``true``; it violates the invariant only over a stored ``false``.

    So a permissive rule would accept or refuse the IDENTICAL request depending
    on data the caller cannot see. An agent cannot predict that and cannot learn
    it from one refusal -- it reads as flakiness. Refusing the whole half-pair is
    decidable from the request alone, every time, and costs only the one harmless
    call above, which an agent has no reason to make on its own.

    This refusal exists ONLY under the flag. With ``patch_fields`` off -- every
    caller that exists today -- it is never reached, so no call that succeeds
    now begins to fail.
    """
    has_blocked = "blocked" in raw
    has_reason = "blocked_reason" in raw
    if has_blocked == has_reason:
        return []

    supplied, missing = ("blocked_reason", "blocked") if has_reason else ("blocked", "blocked_reason")
    return [
        _fail(
            f"items[{idx}].{supplied}",
            f"items[{idx}].{supplied} needs items[{idx}].{missing} in the same item when patch_fields is on -- "
            f"the block state and its note are patched together (send both, or neither)",
            patch_fields_pair=["blocked", "blocked_reason"],
        )
    ]


def _check_item(
    raw: Any, idx: int, *, patch_fields: bool = False
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Validate ONE roadmap-item payload, collecting every blocker it carries.

    Under ``patch_fields`` the normalized row also records WHICH metadata keys
    the payload literally supplied, because an omitted key and an explicitly
    empty one are different instructions (BE-9477) and normalization alone
    cannot tell them apart afterwards -- both arrive as the default.
    """
    if not isinstance(raw, dict):
        return None, [_fail(f"items[{idx}]", f"items[{idx}] must be an object")]

    failures: list[dict[str, Any]] = []
    if patch_fields:
        failures.extend(_check_patch_pairing(raw, idx))

    item_type = raw.get("item_type")
    if item_type not in VALID_ROADMAP_ITEM_TYPES:
        failures.append(
            _fail(
                f"items[{idx}].item_type",
                f"items[{idx}].item_type '{item_type}' invalid. Valid: {sorted(VALID_ROADMAP_ITEM_TYPES)}",
                valid_item_types=sorted(VALID_ROADMAP_ITEM_TYPES),
            )
        )
        # Unknown discriminator: the id branch below cannot be decided, but the
        # remaining independent fields still can be, so keep checking them.
        item_type = None

    project_id = raw.get("project_id") or None
    task_id = raw.get("task_id") or None
    if item_type == "project":
        if not project_id:
            failures.append(_fail(f"items[{idx}].project_id", f"items[{idx}] item_type=project requires project_id"))
        else:
            failures.extend(_check_ref(project_id, f"items[{idx}].project_id"))
        task_id = None
    elif item_type == "task":
        if not task_id:
            failures.append(_fail(f"items[{idx}].task_id", f"items[{idx}] item_type=task requires task_id"))
        else:
            failures.extend(_check_ref(task_id, f"items[{idx}].task_id"))
        project_id = None

    sort_order, sort_failures = _check_sort_order(raw.get("sort_order", 0), idx)
    failures.extend(sort_failures)

    risk = raw.get("risk") or None
    if risk is not None and risk not in VALID_ROADMAP_RISKS:
        failures.append(
            _fail(
                f"items[{idx}].risk",
                f"items[{idx}].risk '{risk}' invalid. Valid: {sorted(VALID_ROADMAP_RISKS)}",
                valid_risks=sorted(VALID_ROADMAP_RISKS),
            )
        )

    complexity = raw.get("complexity") or None
    if complexity is not None and complexity not in VALID_ROADMAP_COMPLEXITIES:
        failures.append(
            _fail(
                f"items[{idx}].complexity",
                f"items[{idx}].complexity '{complexity}' invalid. Valid: {sorted(VALID_ROADMAP_COMPLEXITIES)}",
                valid_complexities=sorted(VALID_ROADMAP_COMPLEXITIES),
            )
        )

    blocked, blocked_reason, blocked_failures = _check_blocked(raw.get("blocked"), raw.get("blocked_reason"), idx)
    failures.extend(blocked_failures)

    if failures:
        return None, failures

    row = {
        "item_type": item_type,
        "project_id": str(project_id) if project_id else None,
        "task_id": str(task_id) if task_id else None,
        "sort_order": sort_order,
        "risk": risk,
        "complexity": complexity,
        "blocked": blocked,
        "blocked_reason": blocked_reason,
    }
    if patch_fields:
        row[PATCH_FIELDS_KEY] = frozenset(f for f in PATCHABLE_ITEM_FIELDS if f in raw)
    return row, []


def collect_items(items: Any, *, patch_fields: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(normalized, failures)`` for a roadmap-item list. Never raises."""
    if not isinstance(items, list):
        return [], [_fail("items", "items must be a list of roadmap-item objects")]

    normalized: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for idx, raw in enumerate(items):
        row, row_failures = _check_item(raw, idx, patch_fields=patch_fields)
        if row_failures:
            failures.extend(row_failures)
        else:
            normalized.append(row)
    return normalized, failures


def validate_items(items: Any, *, patch_fields: bool = False) -> list[dict[str, Any]]:
    """Validate + normalize a list of roadmap-item payloads.

    Raises ValidationError (→ 422) naming EVERY membership / type / range
    failure in the batch, so a malformed agent payload never reaches a DB
    constraint as a 500 and never costs more than one round trip to diagnose.
    """
    normalized, failures = collect_items(items, patch_fields=patch_fields)
    if failures:
        raise_roadmap_failures(failures, operation="upsert_roadmap_items")
    return normalized


# ---------------------------------------------------------------------------
# reorder / remove
# ---------------------------------------------------------------------------


def validate_reorder(updates: Any) -> list[dict[str, Any]]:
    """Validate a reorder payload: list of {id, sort_order}."""
    if not isinstance(updates, list):
        raise ValidationError(
            message="items must be a list of {id, sort_order} objects",
            context={"operation": "reorder_roadmap"},
        )
    normalized: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for idx, raw in enumerate(updates):
        if not isinstance(raw, dict) or not raw.get("id"):
            failures.append(_fail(f"items[{idx}]", f"items[{idx}] must be an object with a non-empty id"))
            continue
        sort_order, sort_failures = _check_sort_order(raw.get("sort_order", 0), idx)
        if sort_failures:
            failures.extend(sort_failures)
            continue
        normalized.append({"id": str(raw["id"]), "sort_order": sort_order})
    if failures:
        raise_roadmap_failures(failures, operation="reorder_roadmap")
    return normalized


def _check_remove_ref(raw: Any, idx: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not isinstance(raw, dict):
        return None, [_fail(f"remove[{idx}]", f"remove[{idx}] must be an object")]

    failures: list[dict[str, Any]] = []
    item_type = raw.get("item_type")
    if item_type not in VALID_ROADMAP_ITEM_TYPES:
        failures.append(
            _fail(
                f"remove[{idx}].item_type",
                f"remove[{idx}].item_type '{item_type}' invalid. Valid: {sorted(VALID_ROADMAP_ITEM_TYPES)}",
                valid_item_types=sorted(VALID_ROADMAP_ITEM_TYPES),
            )
        )
        item_type = None

    project_id = raw.get("project_id") or None
    task_id = raw.get("task_id") or None
    if item_type == "project":
        if not project_id:
            failures.append(_fail(f"remove[{idx}].project_id", f"remove[{idx}] item_type=project requires project_id"))
        else:
            failures.extend(_check_ref(project_id, f"remove[{idx}].project_id"))
        task_id = None
    elif item_type == "task":
        if not task_id:
            failures.append(_fail(f"remove[{idx}].task_id", f"remove[{idx}] item_type=task requires task_id"))
        else:
            failures.extend(_check_ref(task_id, f"remove[{idx}].task_id"))
        project_id = None

    if failures:
        return None, failures
    return {
        "item_type": item_type,
        "project_id": str(project_id) if project_id else None,
        "task_id": str(task_id) if task_id else None,
    }, []


def collect_remove(remove: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(normalized, failures)`` for a removal-ref list. Never raises."""
    if remove is None:
        return [], []
    if not isinstance(remove, list):
        return [], [_fail("remove", "remove must be a list of {item_type, project_id|task_id} objects")]

    normalized: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for idx, raw in enumerate(remove):
        ref, ref_failures = _check_remove_ref(raw, idx)
        if ref_failures:
            failures.extend(ref_failures)
        else:
            normalized.append(ref)
    return normalized, failures


def validate_remove(remove: Any) -> list[dict[str, Any]]:
    """Validate + normalize a list of removal references (0006).

    Each ref mirrors the upsert item contract — ``{item_type, project_id |
    task_id}`` — so the agent removes by the SAME project/task id it ranks
    by, never by an opaque roadmap_item id. No unvalidated agent input: the
    discriminator membership + the required id are checked at the boundary
    (→ 422), never a DB constraint 500. ``None`` normalizes to ``[]``.
    """
    normalized, failures = collect_remove(remove)
    if failures:
        raise_roadmap_failures(failures, operation="remove_roadmap_items")
    return normalized


def validate_upsert_payload(
    items: Any, remove: Any, *, patch_fields: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate BOTH halves of an ``update_roadmap_metadata`` call at once.

    ``upsert_metadata`` used to call ``validate_items`` then ``validate_remove``,
    so a payload wrong in both lists cost two round trips to learn about. One
    call, one rejection, every blocker named (BE-9474).

    ``patch_fields`` only reaches the items half: a removal ref names a row, it
    does not carry metadata, so there is nothing about it to patch.
    """
    normalized_items, item_failures = collect_items(items, patch_fields=patch_fields)
    normalized_remove, remove_failures = collect_remove(remove)
    failures = item_failures + remove_failures
    if failures:
        raise_roadmap_failures(failures, operation="upsert_roadmap_items")
    return normalized_items, normalized_remove
