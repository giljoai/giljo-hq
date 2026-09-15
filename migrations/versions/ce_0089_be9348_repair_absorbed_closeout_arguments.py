# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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

_RESIDUE_MARKER = "</summary>"

_RECOVERABLE_COLUMNS = ("tags", "git_commits", "key_outcomes", "decisions_made")

_MARKUP_TAG = re.compile(r"<[^>]*>")
_QUOTED_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
_JSON_PUNCTUATION = re.compile(r"[\[\]{}:,\s]")
_VALUE_OPENER = re.compile(r"[\[{\"]")
_JSON_SCALAR = re.compile(r"\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_VALUE_TOKEN = re.compile(r"[\[{\"]|\b(?:true|false|null)\b|-?\d")
_PARAMETER_NAME_TAG = re.compile(r'<parameter\s+name="(\w+)"', re.IGNORECASE)
_ARGUMENT_TAG = re.compile(r'<parameter\s+name="(\w+)"\s*>|<(\w+)>')


def _tail_is_pure_call_syntax(tail: str) -> bool:
    without_tags = _MARKUP_TAG.sub(" ", tail)
    scalars_are_credible = _PARAMETER_NAME_TAG.search(tail) is not None
    if not (_VALUE_TOKEN if scalars_are_credible else _VALUE_OPENER).search(without_tags):
        return False
    stripped = _QUOTED_STRING.sub(" ", without_tags)
    if scalars_are_credible:
        stripped = _JSON_SCALAR.sub(" ", stripped)
    return _JSON_PUNCTUATION.sub("", stripped) == ""


def _recover_arguments(tail: str) -> dict[str, list] | None:
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

        if not _tail_is_pure_call_syntax(tail):
            skipped_not_pure += 1
            continue

        recovered = _recover_arguments(tail)
        if not recovered:
            skipped_unparseable += 1
            continue

        if any(not _is_empty(row[name]) for name in recovered):
            skipped_occupied += 1
            continue

        assert all(name in _RECOVERABLE_COLUMNS for name in recovered), recovered
        assignments = ", ".join(f"{name} = CAST(:{name} AS JSONB)" for name in recovered)
        params = {name: json.dumps(value) for name, value in recovered.items()}
        params["row_id"] = row["id"]
        conn.execute(
            sa.text(f"UPDATE product_memory_entries SET {assignments} WHERE id = :row_id"),  # noqa: S608
            params,
        )
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
    pass
