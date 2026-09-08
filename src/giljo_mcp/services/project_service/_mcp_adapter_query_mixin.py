# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP-tool list/projection adapter mixin for ProjectService (BE-6005 split).

Holds the agent-facing READ path extracted from ``McpAdapterMixin`` to keep that
module under the 800-line guardrail: ``list_projects_for_mcp`` (server-side
filtering + projection) and its projection helper ``_build_mcp_project_list``,
plus the module-level helpers they exclusively use (the ceiling / forensic-cap
constants). Composed into ``ProjectService`` alongside ``McpAdapterMixin``;
references ``self.*`` only and resolves shared class attributes (``_VALID_*`` /
``_MODE_TO_PROJECTION`` / ``_MEMORY_LIMIT_CAP``) and helpers
(``_get_valid_project_types`` / ``_extract_git_commits`` / ``self.query`` /
``self.list_projects``) via the MRO. Behavior is byte-identical to the
pre-split single-file mixin.

BE-9468 moved the caller-facing BOUNDS out to ``_mcp_list_bounds`` to keep this module
under the same 800-line guardrail: the ``limit`` constants and validation, the row cut,
the truncation detail block, and the response assembly that decides which bound to name.
The defensive ceiling constant stays HERE because BE-9455 Symptom A's regression suite
patches it on this module -- see that module's docstring for why splitting it would have
produced a green suite asserting a ceiling the code never used.

BE-9471 moved the payload-size diagnostic log (``_log_payload_size_breakdown``, no
``self`` dependency beyond the logger) out to ``_mcp_list_diagnostics``, and the
lifecycle-hidden advice check out to ``_mcp_lifecycle_advice`` -- both for the same
800-line reason: extract, never shed, never raise.
"""

import logging
from datetime import datetime
from typing import Any

from giljo_mcp.domain.project_status import (
    LIFECYCLE_FINISHED_STATUSES,
    ProjectStatus,
)
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.repositories.project_repository import ProjectRepository
from giljo_mcp.services._mcp_wire_bounds import worst_case_cursor_charge
from giljo_mcp.services.project_service._mcp_lifecycle_advice import (
    attach_lifecycle_hidden_advice,
    has_narrowing_filter,
)
from giljo_mcp.services.project_service._mcp_list_bounds import (
    apply_row_limit,
    build_counts_block,
    build_list_response,
    mint_next_cursor,
    open_cursor_walk,
)
from giljo_mcp.services.project_service._mcp_list_diagnostics import log_payload_size_breakdown
from giljo_mcp.services.project_service._mcp_list_filters import (
    _apply_post_fetch_filters,
    resolve_list_projects_query_filters,
)


logger = logging.getLogger(__name__)

# BE-6071 F6a: defensive ceiling on the agent-facing project list. This is a
# SAFETY CAP, not pagination — it bounds a pathological all-tenant fan-out
# without changing normal behavior (a tenant under the ceiling sees the identical
# list).
#
# BE-9455 Symptom A raised it 1000 -> 2500, from a measurement rather than from
# clearing the tenant that reported the bug. Timed on the full agent-facing call,
# three reads after a warm-up, on seeded data against real Postgres:
#
#     rows     median     response
#     1,147     273 ms      297 KB
#     2,500     447 ms      650 KB
#     5,000     494 ms     1.30 MB
#    10,000     845 ms     2.61 MB
#    20,000   1,389 ms     5.25 MB
#
# **The binding constraint is response SIZE, not latency.** Latency alone would
# justify 5,000 (494 ms is the same order as 273 ms). This list is agent-facing: a
# response that overflows the caller's context window is not an honest large answer,
# it is a second silent failure, and worse than the first because the truncation flag
# below is INSIDE the payload that blew the window.
#
# BE-9468 — **THE TOKEN ARITHMETIC THAT ONCE STOOD HERE WAS WRONG AND IS CORRECTED.**
# The original comment converted the byte column above with the house ``chars // 4``
# convention and concluded *"2,500 lands at ~163k tokens, inside a 200k window with
# working room."* **``chars // 4`` does not hold for this payload and it fails in the
# reassuring direction.** Measured on the REAL wire serializer —
# ``pydantic_core.to_json(data, fallback=str).decode()``, compact JSON, reached via
# FastMCP's ``_convert_to_content`` — with a real BPE tokenizer, an actual depth-0
# response runs **2.74 characters per token**, not 4.0, because identifiers tokenize
# worst of all: a 38-char UUID is 23 tokens and a 32-char ISO timestamp is 19, while
# prose runs ~4.5-4.7. Two thirds of an index row is identifier and timestamp.
#
# Restating the same byte column at the measured ratio:
#
#     rows      response     claimed (÷4)     MEASURED (2.6-3.1 chars/token)
#     1,147       297 KB          ~74k              97k - 114k
#     2,500       650 KB         ~163k             212k - 250k
#     5,000      1.30 MB         ~326k             424k - 501k
#
# **So 2,500 rows does NOT fit a 200k context window at either end of the measured
# range — the number this ceiling was chosen to stay under.** Even at a flattering
# 4.0 chars/token it is 81% of the window for a single tool call, with the system
# prompt, the tool schemas and the whole conversation still to fit. The ceiling is not
# the safe margin the original arithmetic believed.
#
# **It is deliberately NOT lowered.** It remains the BE-6071 F6a fan-out guard, and
# lowering it would re-open BE-9455's wound at a smaller number. The real answer is
# that a caller should not be asking for 2,500 rows at all, which is why BE-9468 added
# a bounded caller-facing ``limit`` (below) that binds long before this does. **Do not
# convert bytes to tokens with ÷4 anywhere on this surface.**
#
# A row cap is also, structurally, not a size bound: at ``depth >= 1`` the projection
# adds ``description`` and ``mission`` in full, so ONE row is arbitrarily large.
# Measured: a single ``mode='planning'`` row with a 9,000-char description is ~1,976
# tokens, more than twice an entire ten-row index response. ``2,500 rows x unbounded
# row size`` is an unbounded response regardless of this constant, which is meaningful
# at depth 0 and close to decorative for every richer mode.
#
# **The ceiling is a margin, not the cure.** The reported bug — completed projects
# absent from the agent-facing list — is fixed by the ORDERING change, not by this
# number: once a completion-oriented read truncates on completion recency, the most
# recently completed rows stop being the ones discarded at ANY ceiling value. The
# regression suite proves that independently, with the ceiling patched to 4.
#
# The cap is NOT removed and must not be — it is real protection against an
# all-tenant fan-out. It is made HONEST instead: the cut now selects on the axis the
# caller asked about (``_is_completion_oriented``), and a truncated response says so
# in the response body, not only in a server log the caller will never see. The floor
# is pinned by tests/integration/test_be9455a_project_ceiling_honesty.py so the value
# cannot drift back down without the reasoning that raised it.
_MCP_LIST_PROJECT_CEILING = 2500

# BE-6071 F6c: hard cap on the per-project message history serialized in the
# depth>=3 (forensic) projection. Forensic mode is an operator deep-dive; a
# most-recent window is acceptable and de-fangs the historic 63K-overflow.
_FORENSIC_MESSAGE_CAP = 200


def _resolve_inner_status(
    status_list: list[str] | None,
    include_completed: bool,
    has_completion_filter: bool = False,
) -> str | list[str] | None:
    """SQL-side status filter for the agent list (Seq 161 / IMP-5036 pushdown).

    - explicit ``status`` -> pushed to the repo IN clause (single value or list);
    - ``include_completed`` -> ``None`` so the repo's bare-tenant path keeps the
      archived buckets (cancelled+completed) visible (include_cancelled=True);
    - default agent view -> the lifecycle-ACTIVE complement, excluding every
      lifecycle-finished state (completed/cancelled/terminated/deleted/superseded)
      at the SQL boundary instead of post-fetch.

    BE-9343 (audit F2) -- ``has_completion_filter`` (a ``completed_after`` /
    ``completed_before`` bound was supplied) implies ``include_completed``. A
    completion-date filter is an unambiguous request for FINISHED projects, but
    without this the default branch below excluded every completed project at the
    SQL boundary, so the query returned the projects NOT marked completed and
    dropped the ones that were. Before BE-9343 that returned nothing (every
    ``completed_at`` was NULL), which reads as "nothing found"; after the backfill
    it would have returned an INVERTED set, which reads as an answer -- the worse
    failure of the two, and the reason this is fixed at the mechanism rather than
    documented. An explicit ``status`` still wins, so
    ``list_projects(status="active", completed_after=X)`` keeps its narrow filter.

    Reachable by design: ``template_seeder.py`` seeds the orchestrator's
    duplicate/continuation check with ``completed_after`` and marks
    ``include_completed`` optional, so omitting it is documented-normal.
    """
    if status_list is not None:
        return status_list[0] if len(status_list) == 1 else status_list
    if include_completed or has_completion_filter:
        return None
    return sorted({s.value for s in ProjectStatus} - {s.value for s in LIFECYCLE_FINISHED_STATUSES})


def _is_completion_oriented(
    status_list: list[str] | None,
    include_completed: bool,
    has_completion_filter: bool,
) -> bool:
    """Is this read ASKING ABOUT completed work? (BE-9455 Symptom A.)

    Decides which axis the defensive ceiling truncates on. A cap is a choice about
    which rows to throw away, and making that choice on a different column from the
    caller's question is what hid 145 completed projects: the newest-**created**
    1000 were kept, so a project created in April and completed in July fell outside
    the window and was absent -- not last -- from the answer.

    True when the caller asked about completion:
    - a ``completed_after`` / ``completed_before`` bound (unambiguous);
    - an explicit ``status`` containing ``completed``;
    - ``include_completed=True`` (the "what did we ship" call).

    Precedence deliberately mirrors ``_resolve_inner_status`` exactly, so the
    ordering can never disagree with the filter it orders: an explicit ``status``
    wins over both other signals, which keeps ``list_projects(status="active",
    completed_after=X)`` a narrow non-completion read in BOTH functions. If that
    precedence is ever changed, change it in both or they will drift apart.
    """
    if status_list is not None:
        return ProjectStatus.COMPLETED.value in status_list
    return include_completed or has_completion_filter


class McpAdapterQueryMixin:
    """Agent-facing MCP list + projection path. Composed into ProjectService alongside McpAdapterMixin."""

    async def _fetch_under_ceiling(
        self,
        *,
        inner_status: str | list[str] | None,
        tenant_key: str,
        product_id: str,
        completion_oriented: bool,
        search: str | None = None,
        after_key: tuple[Any, str] | None = None,
    ) -> tuple[list, bool]:
        """Fetch the product's projects under the defensive ceiling. Returns ``(rows, truncated)``.

        BE-6071 F6a put the ceiling here as a safety cap against a pathological
        all-tenant fan-out, NOT as pagination — a tenant under it sees the identical
        list.

        BE-9455 Symptom A: **the cap truncates on the axis the caller asked about.** A
        LIMIT is a decision about which rows to throw away, and the repo's
        ``created_at DESC`` limit-fallback made that decision on a different column from
        the caller's question, so a completion-oriented read silently discarded the
        recent completions it existed to return. A completion-oriented read is now
        ordered by completion recency; every other read keeps the created_at fallback
        untouched, because an active project's ``completed_at`` is NULL and creation
        recency is the only meaningful axis it has.

        ``truncated`` is conservative by construction: a row count landing EXACTLY on
        the ceiling reports truncated even though nothing was dropped. Telling a caller
        its complete list might be short is a harmless error; the alternative is a
        second COUNT query on every call to remove all doubt.
        """
        rows = await self.list_projects(
            status=inner_status,
            tenant_key=tenant_key,
            include_cancelled=True,
            product_id=product_id,
            search=search,
            sort_key=ProjectRepository.COMPLETION_RECENCY_SORT_KEY if completion_oriented else None,
            limit=_MCP_LIST_PROJECT_CEILING,
            # BE-9469: the continuation position. Applied in SQL BEFORE the ceiling, so
            # each page fetches the next ceiling-sized window FROM the cursor. A
            # skip-inside-the-window cursor would cap every walk at the first
            # _MCP_LIST_PROJECT_CEILING rows while reporting normal completion.
            after_key=after_key,
        )
        truncated = len(rows) >= _MCP_LIST_PROJECT_CEILING
        if truncated:
            logger.warning(
                "list_projects_for_mcp hit the %d-project defensive ceiling for tenant %s "
                "(product %s); the agent-facing list is truncated. The response carries "
                "truncated=true so the caller can see it too. This signals an unusually "
                "large project set worth retention review.",
                _MCP_LIST_PROJECT_CEILING,
                tenant_key,
                product_id,
            )
        return rows, truncated

    async def _matched_across_walk(
        self,
        *,
        after_key: tuple[Any, str] | None,
        cursor_scoped_remaining: int | None,
        fetch_kwargs: dict[str, Any],
        post_filter_kwargs: dict[str, Any],
    ) -> int | None:
        """The whole-filter-set match count, EXCLUDING the cursor (BE-9469 QA, U47-F2).

        On page 1 (no cursor) this IS ``remaining`` -- no extra query, and
        ``matched == remaining`` holds by construction (same fetch, same filters). On a
        later page, only a second, cursor-less walk of the SAME filters can answer "how
        many total" without the server storing anything between calls, so it re-fetches
        from the top (``fetch_kwargs`` carries no ``after_key``) and reapplies the same
        post-fetch filters. Omitted (``None``) under the same R2 rule as ``remaining``: a
        ceiling-bound fetch cannot report this truthfully.
        """
        if after_key is None:
            return cursor_scoped_remaining
        whole_rows, whole_truncated = await self._fetch_under_ceiling(**fetch_kwargs)
        if whole_truncated:
            return None
        return len(_apply_post_fetch_filters(whole_rows, **post_filter_kwargs))

    async def _relaxed_lifecycle_count(
        self,
        fetch_kwargs: dict[str, Any],
        post_filter_kwargs: dict[str, Any],
    ) -> int | None:
        """BE-9471 follow-up: the TRUTHFUL hidden count under the caller's own filter set.

        Reuses ``fetch_kwargs``/``post_filter_kwargs`` verbatim -- the SAME builder
        that produced ``matched_total`` -- with only ``inner_status`` (the SQL-side
        lifecycle predicate) relaxed to ``None``, so this can never drift from the
        filter set the caller actually asked about. ``None`` means the relaxed fetch
        itself hit the defensive ceiling -- unknowable, not zero.
        """
        relaxed_rows, relaxed_truncated = await self._fetch_under_ceiling(**{**fetch_kwargs, "inner_status": None})
        if relaxed_truncated:
            return None
        return len(_apply_post_fetch_filters(relaxed_rows, **post_filter_kwargs))

    async def _board_counts(
        self,
        tenant_key: str,
        product_id: str,
        *,
        returned: int,
        matched: int | None,
        remaining: int | None = None,
    ) -> dict[str, Any]:
        """The BE-9468 keystone: the board-wide counts block for this product.

        Its own short session, deliberately -- the fetch session has already closed by
        the time the response is assembled, and one extra grouped round trip is the
        entire cost of this signal. Measured at **1.65 ms median on a 600-row board**
        (5 reps after a warm-up, real Postgres), against a block that costs 144 tokens.

        ``matched``/``remaining`` arrive as None when the fetch that computed them was
        ceiling-bound, because either would then report the ceiling rather than the
        truth. See ``build_counts_block`` for why a SQL COUNT does not rescue that and
        why absence is the honest answer.

        Routed through ``self.board_counts`` (the service layer) rather than the
        repository, matching how ``_fetch_under_ceiling`` reaches ``self.list_projects``.
        Every read on this adapter goes through the same seam.
        """
        grouped = await self.board_counts(tenant_key=tenant_key, product_id=product_id)
        return build_counts_block(grouped, returned=returned, matched=matched, remaining=remaining)

    def _resolve_legacy_status_filter(
        self, status: str | list[str] | None, status_filter: str | None, include_completed: bool
    ) -> tuple[str | list[str] | None, bool]:
        """Honor legacy ``status_filter`` when the new ``status`` kwarg is unset.

        BE-9470 F2 (U68-F1): when BOTH are passed, ``status`` used to win silently
        (even over ``status_filter='all'``, the only spelling of "everything") and
        status_filter's vocabulary went unvalidated on this path. Now a genuine
        disagreement is REFUSED naming both values; identical values still pass.
        """
        if status_filter is None:
            return status, include_completed
        if status_filter not in self._VALID_STATUS_FILTERS:
            raise ValidationError(
                f"Invalid status_filter '{status_filter}'. "
                f"Must be one of: {', '.join(sorted(self._VALID_STATUS_FILTERS))}",
                context={"operation": "list_projects"},
            )
        if status is None:
            if status_filter == "all":
                # Legacy "all" implies the user wants archived projects too --
                # preserve pre-v1.2.1 behavior for callers still using the old kwarg.
                include_completed = True
            else:
                status = status_filter
            return status, include_completed

        # Both set: refuse a genuine disagreement rather than silently pick one.
        # 'all' (the unrestricted board) always disagrees with any explicit status.
        status_values = {status} if isinstance(status, str) else set(status)
        if status_filter == "all" or status_values != {status_filter}:
            raise ValidationError(
                f"status={status!r} and status_filter={status_filter!r} disagree -- pass "
                "only one. status_filter is legacy; prefer status. Identical values on "
                "both are accepted without conflict.",
                context={"operation": "list_projects", "status": status, "status_filter": status_filter},
            )
        return status, include_completed

    def _resolve_projection_mode(
        self,
        mode: str | None,
        depth: int,
        summary_only: bool,
        memory_limit: int | None,
    ) -> tuple[int, bool, bool, int | None]:
        """Translate agent-facing ``mode`` to ``(depth, summary_only, headlines, memory_limit)``.

        BE-5042: when both ``mode`` and numeric ``depth`` are passed, mode wins.
        BE-9470 F3 (U9-F2/U70-F1): an explicit nonzero ``depth`` now gets that same
        precedence over the ``summary_only=True`` default (mirrors the override two
        lines below); ``depth=0`` (the default) is unaffected.
        """
        headlines = False
        resolved_memory_limit: int | None = None
        if mode is None:
            if depth:
                summary_only = False
            return depth, summary_only, headlines, resolved_memory_limit

        if mode not in self._MODE_TO_PROJECTION:
            raise ValidationError(
                f"Invalid mode '{mode}'. Must be one of: {', '.join(sorted(self._MODE_TO_PROJECTION))}.",
                context={"operation": "list_projects", "mode": mode},
            )
        depth, headlines, default_limit = self._MODE_TO_PROJECTION[mode]
        # Mode implies a full projection pass; override summary_only=True default.
        summary_only = False
        if mode == "audit":
            effective_limit = memory_limit if memory_limit is not None else default_limit
            resolved_memory_limit = min(effective_limit, self._MEMORY_LIMIT_CAP)
        elif mode == "forensic":
            # Forensic has no default cap; honor an explicit caller override.
            resolved_memory_limit = min(memory_limit, self._MEMORY_LIMIT_CAP) if memory_limit is not None else None
        else:
            resolved_memory_limit = default_limit
        return depth, summary_only, headlines, resolved_memory_limit

    async def list_projects_for_mcp(
        self,
        status_filter: str | None = None,  # legacy param (kept for back-compat)
        summary_only: bool = True,
        depth: int = 0,
        tenant_key: str | None = None,
        websocket_manager: Any | None = None,
        # v1.2.1 server-side filtering surface
        status: str | list[str] | None = None,
        project_type: str | list[str] | None = None,
        taxonomy_alias_prefix: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        completed_after: datetime | None = None,
        completed_before: datetime | None = None,
        include_completed: bool = False,
        include_superseded: bool = False,
        hidden: bool | None = None,
        # BE-5042 agent-facing projection mode
        mode: str | None = None,
        memory_limit: int | None = None,
        # BE-9468 read layer: text search + a caller-facing row bound
        query: str | None = None,
        limit: int | None = None,
        # BE-9469: the opaque continuation token from a previous response's
        # truncation.next_cursor. Absent = start at the first page, byte-identical to
        # the shipped behaviour.
        cursor: str | None = None,
        # BE-9499a: explicit product to scope to, validated as tenant-owned. Omitted
        # -> the active product, byte-identical to pre-existing behaviour. See
        # ProductService.resolve_binding_product.
        product_id: str | None = None,
    ) -> dict[str, Any]:
        """List projects via MCP tool with server-side filtering (v1.2.1).

        Default returns only projects in active lifecycle (excludes completed,
        cancelled). The `hidden` field is a per-row UI declutter flag and does
        NOT affect default visibility -- agents see hidden and non-hidden alike.
        Pass include_completed=True to retrieve archived (completed/cancelled)
        projects. Pass hidden=True|False to filter by visibility explicitly.

        BE-9157: ``superseded`` projects (work replaced by a successor) are hidden
        by default -- even under include_completed=True. ``include_superseded=True``
        or an explicit ``status="superseded"`` surfaces them.

        BE-9468 -- ``query`` is a case-insensitive substring across name, id and
        taxonomy_alias, and ``limit`` bounds the rows returned (default
        ``LIST_PROJECTS_LIMIT_DEFAULT``, hard max ``LIST_PROJECTS_LIMIT_MAX``,
        the ``search_memory`` contract). Both are optional and additive; ``query``
        forwards to the server-side matcher BE-6076 already shipped on the repository.
        ``mode="triage"`` now returns a genuinely leaner index row -- see
        ``_build_mcp_project_list``.

        BE-9455 Symptom A -- the response always carries ``truncated: bool``, and a
        ``truncation`` detail block when it is True. The list is bounded by a
        defensive ceiling (``_MCP_LIST_PROJECT_CEILING``); a caller that ignores
        ``truncated`` can reason over a partial list as if it were complete, which is
        the defect this reports. A completion-oriented read (``include_completed``,
        an explicit ``status="completed"``, or a completion-date bound) is ordered by
        completion recency so the ceiling discards the oldest completions rather than
        whichever rows happen to have been created longest ago.

        Combination semantics: different fields AND together; multi-value
        within a field ORs together.

        BE-5042 — projection ``mode`` (agent-facing surface):
            ``triage`` (~depth 0), ``planning`` (~depth 1), ``audit``
            (~depth 2 with memory headlines + agent summaries, default last 5
            memory entries), ``forensic`` (~depth 3, full bodies, no cap).
            ``mode`` wins over numeric ``depth`` when both are passed; numeric
            ``depth`` stays as a back-compat path. ``memory_limit`` (default 5,
            cap 50) tunes audit; forensic ignores the cap unless overridden.

        Legacy ``status_filter`` kwarg (kept for back-compat with pre-v1.2.1
        callers) has narrower exclusion semantics than the new ``status``
        read-side kwarg. ``status_filter`` is validated against
        ``_VALID_STATUS_FILTERS``, which is derived from
        ``_DOMAIN_VALID_UPDATE_STATUSES`` plus the ``"all"`` sentinel — this
        deliberately **excludes ``terminated`` and ``deleted``** because those
        are lifecycle-only terminal states never set via update_project. A
        legacy caller passing ``status_filter="terminated"`` or
        ``status_filter="deleted"`` will hit ``ValidationError``. To query
        terminated/deleted projects, use the new ``status`` kwarg (validated
        against the broader ``_VALID_FILTER_STATUSES`` read-side set). The
        ``status_filter="all"`` sentinel sets ``include_completed=True`` to
        preserve pre-v1.2.1 archived-visible behavior; it does NOT include
        terminated/deleted. New code MUST use ``status`` directly.
        """
        status, include_completed = self._resolve_legacy_status_filter(status, status_filter, include_completed)
        if not isinstance(depth, int) or depth not in self._VALID_DEPTH_LEVELS:
            raise ValidationError(
                f"Invalid depth '{depth}'. Must be an integer 0-3.",
                context={"operation": "list_projects"},
            )

        depth, summary_only, headlines, resolved_memory_limit = self._resolve_projection_mode(
            mode, depth, summary_only, memory_limit
        )

        effective_tenant_key = tenant_key or self.tenant_manager.get_current_tenant()
        ws = websocket_manager or self._websocket_manager

        # ----- Normalize + validate the agent-supplied filters (see _mcp_list_filters) -----
        status_list, project_type_list, query, effective_limit = await resolve_list_projects_query_filters(
            status,
            project_type,
            taxonomy_alias_prefix,
            query,
            limit,
            valid_filter_statuses=self._VALID_FILTER_STATUSES,
            tenant_key=effective_tenant_key,
            get_valid_project_types=self._get_valid_project_types,
        )

        from giljo_mcp.services.product_service import ProductService

        product_service = ProductService(
            db_manager=self.db_manager,
            tenant_key=effective_tenant_key,
            websocket_manager=ws,
        )
        active_product = await product_service.resolve_binding_product(
            product_id, operation="list_projects", action="listed", write=False
        )

        # Seq 161 + IMP-5036: SQL pushdown for the status filter (see helper).
        # BE-9343 (audit F2): a completion-date bound implies include_completed --
        # rationale in _resolve_inner_status.
        has_completion_filter = completed_after is not None or completed_before is not None
        inner_status = _resolve_inner_status(
            status_list,
            include_completed,
            has_completion_filter=has_completion_filter,
        )

        # BE-9455 Symptom A: the ceiling truncates on the axis the caller asked
        # about -- see _fetch_under_ceiling.
        completion_oriented = _is_completion_oriented(status_list, include_completed, has_completion_filter)

        # BE-9469: axis, filter fingerprint and incoming position resolved together, and
        # BEFORE the fetch so a refused token costs no query. See open_cursor_walk.
        cursor_axis, cursor_fingerprint, after_key = open_cursor_walk(
            cursor,
            completion_oriented=completion_oriented,
            product_id=active_product.id,
            status_list=status_list,
            include_completed=include_completed,
            include_superseded=include_superseded,
            hidden=hidden,
            project_type_list=project_type_list,
            taxonomy_alias_prefix=taxonomy_alias_prefix,
            created_after=created_after,
            created_before=created_before,
            completed_after=completed_after,
            completed_before=completed_before,
            query=query,
        )

        fetch_kwargs = {
            "inner_status": inner_status,
            "tenant_key": effective_tenant_key,
            "product_id": active_product.id,
            "completion_oriented": completion_oriented,
            "search": query,
        }
        product_projects, truncated = await self._fetch_under_ceiling(**fetch_kwargs, after_key=after_key)

        # BE-9157: hide superseded by default even when include_completed=True
        # surfaced them (inner_status=None). An explicit status request wins.
        superseded_explicitly_requested = status_list is not None and ProjectStatus.SUPERSEDED.value in status_list
        post_filter_kwargs = {
            "exclude_superseded": not include_superseded and not superseded_explicitly_requested,
            "hidden": hidden,
            "project_type_list": project_type_list,
            "taxonomy_alias_prefix": taxonomy_alias_prefix,
            "created_after": created_after,
            "created_before": created_before,
            "completed_after": completed_after,
            "completed_before": completed_before,
        }
        filtered = _apply_post_fetch_filters(product_projects, **post_filter_kwargs)

        # BE-9468: the caller-facing row bound (_mcp_list_bounds.apply_row_limit; not a
        # SQL LIMIT, must never re-sort). BE-9469 QA (U47-F2): cursor-SCOPED, so this
        # becomes ``remaining`` -- see ``_matched_across_walk`` for the constant ``matched``.
        filtered, remaining, limit_truncated = apply_row_limit(filtered, effective_limit)
        matched_total = await self._matched_across_walk(
            after_key=after_key,
            cursor_scoped_remaining=None if truncated else remaining,
            fetch_kwargs=fetch_kwargs,
            post_filter_kwargs=post_filter_kwargs,
        )

        effective_depth = 0 if summary_only else depth

        projects_out = await self._build_mcp_project_list(
            filtered,
            effective_depth,
            effective_tenant_key,
            headlines=headlines,
            memory_limit=resolved_memory_limit,
            index_row=mode == "triage",
        )

        counts = await self._board_counts(
            effective_tenant_key,
            active_product.id,
            returned=len(projects_out),
            matched=matched_total,
            # Withheld when the ceiling bound the fetch -- see _board_counts.
            remaining=None if truncated else remaining,
        )
        # BE-9471: counts.advice, attached BEFORE build_list_response -- see _mcp_lifecycle_advice.
        await attach_lifecycle_hidden_advice(
            counts,
            project_type_list=project_type_list,
            default_lifecycle_view=status_list is None and not include_completed and not has_completion_filter,
            matched=matched_total,
            any_filter_set=has_narrowing_filter(query, post_filter_kwargs),
            relaxed_count=lambda: self._relaxed_lifecycle_count(fetch_kwargs, post_filter_kwargs),
        )
        response = build_list_response(
            projects_out=projects_out,
            # The token is minted by the assembler AFTER its size cut, because it must name
            # the last row actually delivered -- a token minted here would point past rows
            # the size backstop dropped. The charge is an upper-bound placeholder so the
            # ceiling is still charged for the token it will carry.
            cursor_charge=worst_case_cursor_charge(cursor_axis, cursor_fingerprint),
            mint_cursor=lambda rows: mint_next_cursor(
                returned_rows=rows,
                fetched_rows=product_projects,
                matched=remaining,
                ceiling_truncated=truncated,
                axis=cursor_axis,
                fingerprint=cursor_fingerprint,
            ),
            counts=counts,
            ceiling=_MCP_LIST_PROJECT_CEILING,
            product_id=active_product.id,
            depth=effective_depth,
            mode=mode,
            ceiling_truncated=truncated,
            ceiling_rows_fetched=len(product_projects),
            limit_truncated=limit_truncated,
            effective_limit=effective_limit,
            completion_oriented=completion_oriented,
        )

        # IMP-5036 task 696cf625: surface the post-strip payload-size signal
        # for the historical 63K-overflow culprit hunt. Per-row breakdown of
        # the largest contributing field (description/mission/memory_entries/etc.)
        # lands at DEBUG — the culprit hunt is done, so it stays out of the
        # operational INFO log; flip the logger to DEBUG to chart it again.
        log_payload_size_breakdown(self._logger, projects_out, effective_depth, mode)

        return response

    async def _build_mcp_project_list(
        self,
        projects: list,
        depth: int,
        tenant_key: str,
        headlines: bool = False,
        memory_limit: int | None = None,
        index_row: bool = False,
    ) -> list[dict[str, Any]]:
        """Build project list dicts with graduated detail based on depth level.

        BE-9468: ``index_row`` is the genuinely lean projection behind ``mode="triage"``.
        It drops ``series_number`` and nothing else, because nothing else is droppable
        without losing information -- see the field-cost note on the row build below.
        Defaults False, so the ``summary_only=True`` default and every numeric-depth
        caller keep the exact shape they have today.

        BE-5042: ``headlines`` and ``memory_limit`` propagate to the query
        service so audit mode can request a lean projection without forking
        the read path.

        BE-6071 F6b: the per-call (depth 1-2) enrichment facets are fetched in
        ONE grouped query each across ALL listed project_ids (BE-6066 grouped-IN
        pattern), then assembled per-project from the maps — instead of one query
        per project per facet (the N+1). The depth-3 forensic message history
        stays per-project on purpose (see below).
        """
        project_ids = [p.id for p in projects]

        # One grouped query per hot facet, up front — not N per facet.
        agent_summary_map: dict[str, dict] = {}
        agent_details_map: dict[str, list] = {}
        memory_entries_map: dict[str, list] = {}
        if project_ids:
            if depth >= 1:
                agent_summary_map = await self.query.get_project_agent_summaries(project_ids, tenant_key)
            if depth >= 2:
                agent_details_map = await self.query.get_project_agent_details_batch(
                    project_ids, tenant_key, headlines=headlines
                )
                memory_entries_map = await self.query.get_project_memory_entries_batch(
                    project_ids, tenant_key, headlines=headlines, limit=memory_limit
                )

        results = []
        for p in projects:
            item: dict[str, Any] = {
                "project_id": p.id,
                "name": p.name,
                "status": p.status,
                "project_type": getattr(p.project_type, "abbreviation", None) if p.project_type else None,
                "taxonomy_alias": p.taxonomy_alias,
                "created_at": p.created_at,
                "completed_at": p.completed_at,
            }
            # BE-9468: ``mode="triage"`` is documented as the cheapest projection and
            # measured byte-IDENTICAL to the default -- it resolved to the same depth 0.
            # A projection that advertises a cost it does not have is a dishonest signal,
            # so the index row is made real rather than the claim withdrawn.
            #
            # ``series_number`` is the ONLY field removed, and removing it loses NOTHING:
            # it is fully derivable from ``taxonomy_alias``, which the index row keeps
            # (alias "BE-9468" IS type BE and series 9468). Every other field is either
            # the identity the caller must have to act, or a date any ordering question
            # needs.
            #
            # **The honest size of this win is 5.1%**, measured per-field on the real
            # wire serializer: of 79 tokens in an index row, ``project_id`` is 26 and
            # ``created_at`` is 19 -- 57% of the row is irreducible identifier and
            # timestamp, and ``series_number`` is 4. A leaner row is NOT where this
            # surface gets affordable; fewer rows is. That is why ``limit`` above, not
            # this, is the load-bearing change. Stated here so the next reader does not
            # mistake a truthfulness fix for a performance one.
            if not index_row:
                item["series_number"] = p.series_number

            if depth >= 1:
                item["description"] = p.description or ""
                item["mission"] = getattr(p, "mission", None) or ""
                item["agent_summary"] = agent_summary_map.get(p.id, {"agent_count": 0, "job_types": []})

            memory_entries: list = []
            if depth >= 2:
                memory_entries = memory_entries_map.get(p.id, [])
                item["memory_entries"] = memory_entries
                item["agent_details"] = agent_details_map.get(p.id, [])

            if depth >= 3:
                item["git_commits"] = self._extract_git_commits(memory_entries)
                # BE-6071: depth-3 forensic message history stays PER-PROJECT (not
                # batched). It is already F6c-capped at _FORENSIC_MESSAGE_CAP/project
                # AND forensic is a rare operator deep-dive off the hot path, so the
                # bounded per-project query is acceptable — batching it would require
                # a per-project SQL LIMIT (window function) for the least benefit.
                message_history = await self.query.get_project_messages(
                    project_id=p.id,
                    tenant_key=tenant_key,
                    limit=_FORENSIC_MESSAGE_CAP,
                )
                item["message_history"] = message_history

            results.append(item)
        return results
