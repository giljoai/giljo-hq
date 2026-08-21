# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9348: recover closeout arguments absorbed into ``product_memory_entries.summary``.

Revision ID: ce_0089_be9348_repair_absorbed_closeout_arguments
Revises: ce_0088_backfill_project_completed_at
Create Date: 2026-08-03

A caller's tool-call serialization can merge one argument into the string value of its
neighbour, so the following argument never leaves the caller. When the swallowed
argument was merely OPTIONAL (``tags``, ``git_commits``), every REQUIRED argument was
still present: the call validated, the write boundary capped length but did not reject
call syntax, and the closeout SUCCEEDED. The swallowed argument was lost and the raw
markup was stored verbatim, producing rows shaped like::

    summary: "...filed as INF-9293.</summary>\\n<parameter name=\\"tags\\">[\\"docs\\", \\"chore\\"]"
    tags:    []

BE-9348 fixes the write path at the MCP dispatch seam. This migration repairs the rows
that path already produced. The data was never destroyed -- it was MISFILED into the
summary column -- which is what makes real recovery possible rather than guesswork.

What this migration does NOT claim
----------------------------------
It repairs whatever it finds. It does **not** certify how many damaged rows exist. The
360-memory search that surfaced the known cases returns false negatives on literal
substrings that provably exist, so the damaged set has a measured FLOOR (8 rows in the
test-install database at authoring time) and **no assertable upper bound**. The guard below
also only matches residue containing ``</summary>``; a differently-shaped residue is
simply not seen. Do not read a clean run as proof of a clean database.

Why a migration and not tolerance
---------------------------------
The Data-facing DoD prefers (a) code tolerates the old shape. It cannot help here: the
values are ABSENT from their own columns, so no amount of read-side tolerance restores
``tags`` or ``git_commits``. Only (b), an idempotent existence-guarded rewrite, recovers
them.

This migration NEVER rewrites a summary
---------------------------------------
It recovers the empty columns and leaves ``summary`` exactly as it found it. An earlier
draft also stripped the residue off the prose head, and that was wrong for two reasons.

**It was not decidable.** A legitimate closeout that QUOTES the residue verbatim at the
very end -- while its own ``tags`` column happens to be empty -- is byte-identical to a
genuinely damaged row. No signal separates them, so no amount of gate-tightening fixes
it; the information simply is not in the row. The answer is not to classify better but
to stop doing the irreversible thing when classification is impossible. Recovering an
EMPTY column is additive and hand-reversible; truncating prose is not.

**The residue is the evidence.** It is the only reason these rows were findable at all,
and -- because the 360-memory search returns false negatives on literal substrings that
provably exist -- it is the only way anyone will ever find the ones we could not
enumerate. Destroying it would destroy the audit trail for a damage set we have
explicitly stated we cannot bound. A messy-but-legible summary is strictly better than a
clean one nobody can verify.

Order is still load-bearing: narrowing gate -> parse -> confirm the target column is
empty -> only then write.

Stated limitation, accepted deliberately
----------------------------------------
A closeout that legitimately quotes the residue at the very end AND has an empty
``tags``/``git_commits`` column will have that column populated from the quoted text --
tags it should not have. That is wrong, but it is additive, hand-reversible, and
vanishingly rare, and every row this migration touches is logged with its pre-state
below. This is a knowingly accepted trade, not an oversight.

The detection logic is DUPLICATED, deliberately, not imported
-------------------------------------------------------------
``api.endpoints.mcp_transport`` has the same narrowing rule, and importing it here would
be a mistake. A migration must keep meaning exactly what it meant the day it was
authored; importing runtime code means a later change to the runtime rule silently
rewrites the behaviour of an already-applied historical migration, which is unauditable.
Same precedent as ``ce_0088``'s frozen status literal. These copies are frozen as of this
revision and must NOT be refactored into a shared import.

Idempotent
----------
``WHERE summary LIKE '%</summary>%'`` is the guard. Because the summary is deliberately
left in place, a repaired row STILL matches it on the next run -- but its target column
is now populated, so it takes the "column already populated" branch and nothing is
written. Skipped rows are skipped identically. Both paths are no-ops, so the CE
installer's every-boot ``alembic upgrade head`` re-run is safe. Data-only: every column
here has existed since baseline_v38, so there is no schema change to guard.

Edition Scope: Both -- ``product_memory_entries`` is a CE table (it appears only in
``migrations/versions/``, never in ``saas_versions/``), so this lives in the CE chain.
SaaS inherits it unchanged on its next preDeploy alembic run.
"""

import json
import logging
import re

import sqlalchemy as sa
from alembic import op


revision = "ce_0089_be9348_repair_absorbed_closeout_arguments"
down_revision = "ce_0088_backfill_project_completed_at"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

# The marker that ends the absorbing argument's own value. Everything from here on is
# the caller's leftover call syntax.
_RESIDUE_MARKER = "</summary>"

# JSONB list columns a closeout can carry. Frozen as of this revision -- see the
# module docstring on why this is a literal rather than an import.
_RECOVERABLE_COLUMNS = ("tags", "git_commits", "key_outcomes", "decisions_made")

# Frozen copies of the runtime narrowing rule, string-identical to mcp_transport as of
# this revision. Do NOT replace with an import, and do NOT re-sync them later: divergence
# after this revision ships is EXPECTED and correct, because this file must keep meaning
# what it meant the day it was authored.
_MARKUP_TAG = re.compile(r"<[^>]*>")
_QUOTED_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
_JSON_PUNCTUATION = re.compile(r"[\[\]{}:,\s]")
_VALUE_OPENER = re.compile(r"[\[{\"]")
_JSON_SCALAR = re.compile(r"\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_VALUE_TOKEN = re.compile(r"[\[{\"]|\b(?:true|false|null)\b|-?\d")
_PARAMETER_NAME_TAG = re.compile(r'<parameter\s+name="(\w+)"', re.IGNORECASE)
_ARGUMENT_TAG = re.compile(r'<parameter\s+name="(\w+)"\s*>|<(\w+)>')


def _tail_is_pure_call_syntax(tail: str) -> bool:
    """True when the tail is leftover call syntax AND carries a serialized value.

    Both halves matter. Without the value test, stripping the tag from ordinary prose
    such as "Usage: giljo close <project_id>" leaves an empty string, which satisfies
    the purity test vacuously -- so a legitimate summary that merely mentions a
    placeholder would be treated as damage. The closeout written for BE-9348 itself
    discusses these markers in prose.

    A value is NOT always bracketed: a scalar-valued parameter is absorbed as a bare
    token ('<parameter name="phase">3'). The scalar allowance is gated on the
    serializer's own ``<parameter name="...">`` markup, which narrows it but does NOT
    make it exact -- legitimate prose CAN contain that markup, and

        Confirmed the residue shape: <parameter name="requires_action">true
        Status update: worker mid-task.<parameter name="requires_action">true

    have byte-identical tails, so no tail-based gate can separate them. The gate is a
    cost reduction, not a proof; ungated, a bare digit would additionally misread
    "…<project_id> 2026".

    Only list-valued columns are ever recovered here (``_recover_arguments`` requires a
    leading '['), so the scalar allowance changes no outcome in this migration; it is
    carried to keep this copy identical to the runtime rule it was frozen from.
    """
    without_tags = _MARKUP_TAG.sub(" ", tail)
    scalars_are_credible = _PARAMETER_NAME_TAG.search(tail) is not None
    if not (_VALUE_TOKEN if scalars_are_credible else _VALUE_OPENER).search(without_tags):
        return False
    stripped = _QUOTED_STRING.sub(" ", without_tags)
    if scalars_are_credible:
        stripped = _JSON_SCALAR.sub(" ", stripped)
    return _JSON_PUNCTUATION.sub("", stripped) == ""


def _recover_arguments(tail: str) -> dict[str, list] | None:
    """Parse absorbed argument values out of the residue tail.

    Returns a name -> list mapping, or ``None`` when a recoverable tag is present but
    its payload will not parse (the row is then left completely alone).
    """
    decoder = json.JSONDecoder()
    recovered: dict[str, list] = {}
    for match in _ARGUMENT_TAG.finditer(tail):
        name = match.group(1) or match.group(2)
        if name not in _RECOVERABLE_COLUMNS:
            continue
        rest = tail[match.end() :].lstrip()
        if not rest.startswith("["):
            return None
        try:
            value, _consumed = decoder.raw_decode(rest)
        except ValueError:
            return None
        if not isinstance(value, list):
            return None
        recovered[name] = value
    return recovered


def _is_empty(value) -> bool:
    """A JSONB list column counts as empty when NULL or ``[]``.

    NOT merely ``IS NULL``. Both columns are declared ``JSONB, default=list,
    server_default="[]"`` (``product_memory_entry.py``), so a closeout that lost its
    tags stores ``[]``, never NULL -- every known damaged row is ``[]``. A NULL-only
    guard would match ZERO of them and report a clean, successful, entirely useless
    run. Do not "simplify" this back to a NULL check.
    """
    return value is None or value == []


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, sequence, summary, tags, git_commits, key_outcomes, decisions_made "
            "  FROM product_memory_entries "
            " WHERE summary LIKE '%</summary>%'"
        )
    ).mappings()

    repaired = 0
    skipped_not_pure = 0
    skipped_unparseable = 0
    skipped_occupied = 0

    for row in rows:
        summary = row["summary"] or ""
        marker_at = summary.find(_RESIDUE_MARKER)
        if marker_at == -1:
            continue

        tail = summary[marker_at:]

        # 1. Narrowing gate -- prose that merely QUOTES a marker keeps talking.
        if not _tail_is_pure_call_syntax(tail):
            skipped_not_pure += 1
            continue

        # 2. Parse. Nothing is written yet.
        recovered = _recover_arguments(tail)
        if not recovered:
            skipped_unparseable += 1
            continue

        # 3. Confirm every target column is currently empty. A populated column means
        #    the row carries data this residue disagrees with, so the row is left alone.
        #    This is also what makes a replay a no-op: a row repaired on the previous
        #    run still matches the guard (its summary is deliberately unchanged) and
        #    lands here instead of being written twice.
        if any(not _is_empty(row[name]) for name in recovered):
            skipped_occupied += 1
            continue

        # 4. Recover the columns ONLY. `summary` is deliberately never written -- see
        #    the module docstring: a legitimate closeout quoting the residue is
        #    byte-identical to real damage, and the residue is the audit trail for a
        #    damage set we cannot bound.
        # Column names are interpolated, so pin that they can ONLY ever be the frozen
        # literal above -- _recover_arguments already filters to it, and this makes that
        # guarantee local instead of asking the reader to go and check. Values are always
        # bound parameters, never interpolated.
        assert all(name in _RECOVERABLE_COLUMNS for name in recovered), recovered
        assignments = ", ".join(f"{name} = CAST(:{name} AS JSONB)" for name in recovered)
        params = {name: json.dumps(value) for name, value in recovered.items()}
        params["row_id"] = row["id"]
        conn.execute(
            sa.text(f"UPDATE product_memory_entries SET {assignments} WHERE id = :row_id"),  # noqa: S608
            params,
        )
        # Every touched row is recorded with its PRE-state. Deletion is not the only
        # reversal anyone might need, and a repair that ran months ago with no record of
        # what it changed is its own problem.
        logger.info(
            "ce_0089: repaired entry id=%s sequence=%s -- %s",
            row["id"],
            row["sequence"],
            "; ".join(f"{name}: {row[name]!r} -> {value!r}" for name, value in recovered.items()),
        )
        repaired += 1

    logger.info(
        "ce_0089: repaired %s row(s); skipped %s (prose, not residue), %s (unparseable), %s (column already populated)",
        repaired,
        skipped_not_pure,
        skipped_unparseable,
        skipped_occupied,
    )


def downgrade() -> None:
    """Deliberate no-op -- and, unlike the usual case, very little is at stake.

    This revision only ever ADDS values to columns that were empty; no summary is ever
    rewritten and nothing is deleted. Emptying those columns again would be the literal
    reversal, but nothing distinguishes a column this migration filled from one a
    healthy closeout filled, so a blind downgrade would erase real data to undo
    something harmless.

    A reversal is therefore a hand operation, and the upgrade logs every row it touched
    with its pre-state (id, sequence, before -> after) precisely so that operation is
    possible. Leaving the recovered values in place is safe in both directions: on older
    code they are simply a populated JSONB list, which is the shape an undamaged
    closeout always had.
    """
