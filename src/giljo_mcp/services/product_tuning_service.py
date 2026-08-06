# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
ProductTuningService - On-demand product context drift detection (Handover 0831)

Assembles comparison prompts from current product context vs 360 memory history,
stores agent-submitted tuning proposals, and manages the review lifecycle.

Design: User-initiated, not automatic. GiljoAI assembles context and generates
the comparison prompt. The user's AI coding agent does the reasoning.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.config.defaults import (
    DEFAULT_FIELD_PRIORITY,
    TUNING_SECTION_TOGGLE_MAP,
)
from giljo_mcp.database import DatabaseManager
from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError
from giljo_mcp.models import Product
from giljo_mcp.repositories.product_memory_repository import ProductMemoryRepository
from giljo_mcp.repositories.product_repository import ProductRepository
from giljo_mcp.repositories.user_repository import UserRepository
from giljo_mcp.schemas.jsonb_validators import validate_tuning_state
from giljo_mcp.services._session_helpers import tenant_scoped_session
from giljo_mcp.services.product_field_map import assemble_update_kwargs


logger = logging.getLogger(__name__)

# Maps tuning section keys to product fields for applying proposals.
# Handover 0840c: Rewritten for normalized tables.
# BE-6225d: this map only translates the tuning INPUT vocabulary (section keys) into
# canonical product columns. The column->update_product-block grouping is shared with
# the vision-extraction writer via the product-field translator
# (services/product_field_map.py) -- there is no longer a parallel block mapper to keep
# in sync.
SECTION_FIELD_MAP: dict[str, dict[str, str]] = {
    "description": {"type": "direct", "field": "description"},
    "tech_stack": {
        "type": "relation",
        "relation": "tech_stack",
        "fields": {
            "programming_languages": "programming_languages",
            "frontend_frameworks": "frontend_frameworks",
            "backend_frameworks": "backend_frameworks",
            "databases_storage": "databases_storage",
            "infrastructure": "infrastructure",
            "dev_tools": "dev_tools",
        },
    },
    "architecture": {
        "type": "relation",
        "relation": "architecture",
        "fields": {
            "primary_pattern": "primary_pattern",
            "design_patterns": "design_patterns",
            "api_style": "api_style",
            "architecture_notes": "architecture_notes",
            "coding_conventions": "coding_conventions",
        },
    },
    "tech_stack.backend_frameworks": {
        "type": "relation_field",
        "relation": "tech_stack",
        "field": "backend_frameworks",
    },
    "tech_stack.frontend_frameworks": {
        "type": "relation_field",
        "relation": "tech_stack",
        "field": "frontend_frameworks",
    },
    "tech_stack.programming_languages": {
        "type": "relation_field",
        "relation": "tech_stack",
        "field": "programming_languages",
    },
    "tech_stack.databases_storage": {"type": "relation_field", "relation": "tech_stack", "field": "databases_storage"},
    "tech_stack.infrastructure": {"type": "relation_field", "relation": "tech_stack", "field": "infrastructure"},
    "tech_stack.dev_tools": {"type": "relation_field", "relation": "tech_stack", "field": "dev_tools"},
    "architecture.primary_pattern": {"type": "relation_field", "relation": "architecture", "field": "primary_pattern"},
    "architecture.design_patterns": {"type": "relation_field", "relation": "architecture", "field": "design_patterns"},
    "architecture.api_style": {"type": "relation_field", "relation": "architecture", "field": "api_style"},
    "architecture.architecture_notes": {
        "type": "relation_field",
        "relation": "architecture",
        "field": "architecture_notes",
    },
    "architecture.coding_conventions": {
        "type": "relation_field",
        "relation": "architecture",
        "field": "coding_conventions",
    },
    "core_features": {"type": "direct", "field": "core_features"},
    "brand_guidelines": {"type": "direct", "field": "brand_guidelines"},
    "quality_standards": {"type": "relation_field", "relation": "test_config", "field": "quality_standards"},
    "target_platforms": {"type": "direct", "field": "target_platforms"},
}

TUNING_PROMPT_TEMPLATE = """You are reviewing a product's stored context after recent development work.

This context is STATE + INTENT: it records both what has already been BUILT and what
the user still intends to build. Your review is ADDITIVE. The question is: since the
last review, has anything been BUILT, ADDED, or CHANGED that this context has not
absorbed yet? Hunt the git log, project memory, and dependencies for things to ADD or
UPDATE. Do NOT hunt for context items that are "missing" from the code — an item with
no code behind it yet is a plan, not an error.

## Product
- Name: {product_name}
- ID: {product_id}
{project_path_line}
## MCP Tools Available
- `get_context(categories, product_id)` — retrieve product context (tenant_key is auto-injected, do not pass it)
- `apply_context_tuning(product_id, proposals, overall_summary)` — apply approved changes directly to product fields

## Section authority — read this before judging anything
Different sections answer to different sources of truth:
- **Code-authoritative** (tech_stack, dev_tools, architecture-as-built): the code is the
  source of truth. When the code has moved ahead of the stored value, propose the update freely.
- **Intent-bearing** (description, core_features, quality_standards): these may legitimately
  describe plans that are not built yet. Absence from the code is NOT drift.

## The hard rule (do not break this)
NEVER propose removing an item merely because it is not in the code yet. Context describes
both what exists and what the user intends to build. If an item looks unbuilt, mark it
"planned — not yet built" and ask whether it is still intended. Removal only happens when
the user says the intent changed.

## Phase 1: RESEARCH (do this silently — no output to user yet)

Ground yourself in the actual codebase before making any judgments.{project_path_instruction}

1. File structure:  Run `ls` in the project root, `ls static/` or equivalent
2. Dependencies:   Read requirements.txt (or package.json, go.mod, etc.)
3. Entry point:    Read the first 60 lines of the main backend file to see imports, config, and patterns
4. Tests:          Run this stack's test-discovery/listing command (e.g., a Python
   runner's collect-only flag, `go test -list .` for Go, or your JS/TS runner's
   list-tests flag) to list tests without executing them
5. Git history:    Run `git log --oneline -15` to see recent changes
6. Project memory: Call `get_context(categories=["memory_360"], product_id="{product_id}", depth_config={{"memory_360": {{"shape": "full"}}}})` to get recent project closeout bodies — these describe what was built, decisions made, and outcomes (full shape required since headlines-only would drop the very content this prompt needs)

If you cannot run terminal commands (e.g., web-based agent), skip steps 1-5 and rely on project memory from step 6.

Do NOT present findings yet. Move to Phase 2.

## Phase 2: QUICK SCAN (brief output to user)

Based on your research, give the user a short summary:

```
Scanned the codebase and project history.

New or changed since the last review (candidates to ADD or UPDATE):
- <section_name>: <one-line reason>
- <section_name>: <one-line reason>

Sections that look current:
- <section_name>, <section_name>, ...

Want to review the flagged sections? Or walk through all of them?
```

Wait for the user to respond before continuing.

## Phase 3: INTERACTIVE REVIEW (one section at a time)

For each section the user wants to review, present this format:

```
### <Section Name>

**Current value:**
<the stored value as-is>

**What I found:**
<evidence from code, git log, or project memory>

**Verdict:** ADDED / CONTRADICTION / INTENT
- ADDED — new in the code or history, not yet in this context → propose adding it
- CONTRADICTION — the context claims something the code disproves → propose correcting it
- INTENT — in the context but not in the code → keep it; optionally confirm it is still planned. Never propose removal here.

**Proposed update:**
<full replacement text — or "No change needed">

Does this look right? Want to adjust the wording before I save it?
```

RULES:
- Wait for user approval before moving to the next section
- If the user provides alternative wording, use their version
- If the user says "skip", exclude that section from the final submission
- If the user says "looks good" or similar, mark it as approved and move on
- Keep proposed values factual and concise — avoid marketing language
- Write the COMPLETE replacement value, not a diff or partial edit
- An INTENT verdict is not drift: keep the item, never delete it, and at most ask whether it is still planned

## Phase 4: SUBMIT

After all sections are reviewed, confirm with the user:

```
Ready to submit N approved updates:
- <section>: <brief change summary>
- <section>: <brief change summary>

Submitting now.
```

Then call:

apply_context_tuning(
  product_id="{product_id}",
  proposals=[
    {{
      "section": "<section_key>",
      "verdict": "ADDED|CONTRADICTION|INTENT",
      "drift_detected": true|false,
      "current_summary": "<what it said before>",
      "evidence": "<what code/git/memory shows>",
      "proposed_value": "<the approved replacement text>",
      "confidence": "high|medium|low",
      "reasoning": "<one sentence>"
    }}
  ],
  overall_summary="<one paragraph on context health>"
)

Set drift_detected from the verdict: ADDED and CONTRADICTION are changes to apply, so
drift_detected: true. INTENT keeps the item unchanged, so drift_detected: false and
proposed_value: null.

Confidence levels:
- "high" = verified by reading code or running commands
- "medium" = inferred from project memory / git log only
- "low" = best guess, could not verify

Only include sections the user explicitly approved. Do not include skipped sections.

ALWAYS call apply_context_tuning at the end of the review. If nothing needed adding or correcting, submit a single proposal with the most relevant section (typically 'description'), `verdict: 'INTENT'`, `drift_detected: false`, `proposed_value: null`, `current_summary: '<unchanged value>'`, `evidence: 'Reviewed; the context already reflects what has been built'`, `reasoning: 'Nothing new to absorb — submission records the review timestamp.'`, `confidence: 'high'`. This records the review even when nothing changed.
{vision_note}
## Sections to Review

{current_context}"""

VISION_DOCS_NOTE = """
## Vision Documents — Special Handling
Vision Documents are historical records of original product intent.
Do NOT propose replacing them. Instead, note any divergence between the
vision and current reality, and suggest updates to other sections
(like Description or Core Features) to reflect the current state.
"""


class ProductTuningService:
    """Service for product context tuning: prompt assembly, proposal storage, and review lifecycle."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        tenant_key: str,
        websocket_manager=None,
        test_session: AsyncSession | None = None,
    ):
        self.db_manager = db_manager
        self.tenant_key = tenant_key
        self._websocket_manager = websocket_manager
        self._test_session = test_session
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._memory_repo = ProductMemoryRepository()
        self._product_repo = ProductRepository()
        self._user_repo = UserRepository()

    def _get_session(self):
        """Yield a tenant-scoped DB session, honoring an injected test session (shared helper, BE-8000d)."""
        return tenant_scoped_session(self.db_manager, self.tenant_key, self._test_session)

    async def _get_product(self, session: AsyncSession, product_id: str) -> Product:
        product = await self._product_repo.get_by_id(session, self.tenant_key, product_id, eager_load=True)
        if not product:
            raise ResourceNotFoundError(
                message="Product not found",
                context={"product_id": product_id, "tenant_key": self.tenant_key},
            )
        return product

    async def _get_user_configs(self, session: AsyncSession, user_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Get user's toggle and depth configurations from normalized tables/columns."""
        from giljo_mcp.config.defaults import DEFAULT_CATEGORY_TOGGLES

        user = await self._user_repo.get_user_by_id(session, user_id, self.tenant_key)
        if not user:
            raise ResourceNotFoundError(message="User not found", context={"user_id": user_id})

        # Build toggle_config from user_field_priorities table
        rows = await self._user_repo.get_field_priorities(session, user_id, self.tenant_key)

        if rows:
            toggles = dict(DEFAULT_CATEGORY_TOGGLES)
            for row in rows:
                toggles[row.category] = row.enabled
            priorities = {"product_core": {"toggle": True}, "project_description": {"toggle": True}}
            for cat, enabled in toggles.items():
                priorities[cat] = {"toggle": enabled}
            toggle_config = {"version": "4.0", "priorities": priorities}
        else:
            toggle_config = DEFAULT_FIELD_PRIORITY

        # Build depth_config from columns
        depth_config = {
            "vision_documents": user.depth_vision_documents,
            "memory_last_n_projects": user.depth_memory_last_n,
            "git_commits": user.depth_git_commits,
            "agent_templates": user.depth_agent_templates,
            "tech_stack_sections": user.depth_tech_stack_sections,
            "architecture_depth": user.depth_architecture,
        }

        return toggle_config, depth_config

    def _get_eligible_sections(self, toggle_config: dict[str, Any]) -> list[str]:
        """Return section keys whose parent toggle is ON."""
        priorities = toggle_config.get("priorities", {})
        eligible = []
        for section_key, parent_toggle in TUNING_SECTION_TOGGLE_MAP.items():
            cat_config = priorities.get(parent_toggle, {})
            if isinstance(cat_config, dict) and cat_config.get("toggle", True):
                eligible.append(section_key)
        return eligible

    def _serialize_current_context(self, product: Product, sections: list[str]) -> str:
        """Serialize current product context for selected sections."""
        parts = []
        for section in sections:
            mapping = SECTION_FIELD_MAP.get(section)
            if not mapping:
                continue

            label = section.replace("_", " ").title()

            if mapping["type"] == "direct":
                value = getattr(product, mapping["field"], None)
            elif mapping["type"] == "relation":
                rel_obj = getattr(product, mapping["relation"], None)
                if rel_obj:
                    items = []
                    for field_name in mapping["fields"]:
                        v = getattr(rel_obj, field_name, None)
                        if v:
                            items.append(f"- {field_name}: {v}")
                    value = "\n".join(items) if items else None
                else:
                    value = None
            elif mapping["type"] == "relation_field":
                rel_obj = getattr(product, mapping["relation"], None)
                value = getattr(rel_obj, mapping["field"], None) if rel_obj else None
            else:
                continue

            header = f"### {label}\n**Section key:** `{section}`"

            if value is None:
                parts.append(f"{header}\n(not set)")
            elif isinstance(value, list):
                parts.append(f"{header}\n{', '.join(str(v) for v in value)}")
            else:
                parts.append(f"{header}\n{value}")

        return "\n\n".join(parts) if parts else "(no context sections selected)"

    async def assemble_tuning_prompt(
        self,
        product_id: str,
        user_id: str,
        sections: list[str],
    ) -> dict[str, Any]:
        """
        Assemble a comparison prompt for the user to paste into their AI coding agent.

        Args:
            product_id: Target product ID
            user_id: User ID for toggle/depth config
            sections: List of section keys to include

        Returns:
            Dict with prompt, sections_included, lookback_depth, git_enabled

        Raises:
            ResourceNotFoundError: If product or user not found
            ValidationError: If no valid sections provided
        """
        async with self._get_session() as session:
            product = await self._get_product(session, product_id)
            toggle_config, _ = await self._get_user_configs(session, user_id)

            eligible = self._get_eligible_sections(toggle_config)
            valid_sections = [s for s in sections if s in eligible]

            if not valid_sections:
                raise ValidationError(
                    message="No valid sections selected for tuning",
                    context={"requested": sections, "eligible": eligible},
                )

            current_context = self._serialize_current_context(product, valid_sections)
            vision_note = VISION_DOCS_NOTE if "vision_documents" in valid_sections else ""

            path = getattr(product, "project_path", None) or ""
            project_path_line = f"- Project Path: {path}\n" if path else ""
            project_path_instruction = (
                f"\nThe project is located at: {path}\nRun all file and git commands from that directory."
                if path
                else "\nUse the current working directory for file and git commands."
            )

            prompt = TUNING_PROMPT_TEMPLATE.format(
                product_name=product.name,
                product_id=product_id,
                project_path_line=project_path_line,
                project_path_instruction=project_path_instruction,
                current_context=current_context,
                vision_note=vision_note,
            )

            return {
                "prompt": prompt,
                "sections_included": valid_sections,
                "lookback_depth": None,
                "git_enabled": False,
            }

    async def get_eligible_sections(self, product_id: str, user_id: str) -> list[str]:
        """Get sections eligible for tuning based on user's toggle settings."""
        async with self._get_session() as session:
            await self._get_product(session, product_id)
            toggle_config, _ = await self._get_user_configs(session, user_id)
            return self._get_eligible_sections(toggle_config)

    def _build_update_kwargs(self, proposals: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
        """Convert drift proposals into kwargs for ProductService.update_product().

        Translates each drift proposal's section key into the canonical product
        column(s) it targets (via SECTION_FIELD_MAP), then groups the flat
        ``{column: value}`` mapping into update_product blocks through the shared
        product-field translator (services/product_field_map.py) -- the same translator
        the vision-extraction writer uses.

        Returns (update_kwargs, sections_applied).
        """
        column_values: dict[str, Any] = {}
        sections_applied: list[str] = []

        for proposal in proposals:
            if not proposal.get("drift_detected"):
                continue

            section = proposal.get("section")
            value = proposal.get("proposed_value")
            mapping = SECTION_FIELD_MAP.get(section)
            if not mapping or value is None:
                continue

            if mapping["type"] == "direct":
                field = mapping["field"]
                if field == "target_platforms" and isinstance(value, str):
                    value = [v.strip() for v in value.split(",") if v.strip()]
                column_values[field] = value
            elif mapping["type"] == "relation":
                resolved = self._resolve_relation_columns(section, mapping, value)
                if resolved is None:
                    continue
                column_values.update(resolved)
            elif mapping["type"] == "relation_field":
                column_values[mapping["field"]] = value

            sections_applied.append(section)

        return assemble_update_kwargs(column_values), sections_applied

    def _resolve_relation_columns(
        self,
        section: str,
        mapping: dict[str, Any],
        value: Any,
    ) -> dict[str, Any] | None:
        """Resolve a whole-relation-section proposal into ``{column: value}`` pairs.

        Returns the resolved columns, or ``None`` (with a warning logged) when the
        proposed value cannot be applied -- an unstructured string for a multi-field
        relation, a dict with no recognized fields, or a non-dict/non-string value.
        Mirrors the prior per-section accept semantics; the column->block grouping is
        handled by the shared translator afterwards.
        """
        known_fields = mapping.get("fields", {})

        if isinstance(value, dict):
            if not known_fields:
                return dict(value)
            filtered = {k: v for k, v in value.items() if k in known_fields}
            if filtered:
                return filtered
            self._logger.warning(
                "Skipping relation section '%s': no recognized fields in dict (known: %s)",
                section,
                list(known_fields.keys()),
            )
            return None

        if isinstance(value, str):
            # Agent sent a flat string for a structured relation. Use it as a
            # single-field update only when the relation has exactly one field;
            # otherwise reject with guidance on the sub-section keys.
            field_keys = list(known_fields.keys())
            if len(field_keys) == 1:
                return {field_keys[0]: value}
            self._logger.warning(
                "Skipping relation section '%s': got plain string but section has %d fields. "
                "Use sub-section keys instead: %s",
                section,
                len(field_keys),
                [f"{section}.{f}" for f in field_keys],
            )
            return None

        self._logger.warning(
            "Skipping relation section '%s': expected dict, got %s",
            section,
            type(value).__name__,
        )
        return None

    async def apply_tuning_updates(
        self,
        product_id: str,
        proposals: list[dict[str, Any]],
        overall_summary: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Apply agent-approved tuning proposals directly to product fields.

        Routes all writes through ProductService.update_product() — the same
        validated path used by the Edit Product dialog. Only proposals where
        drift_detected is True are applied.

        Args:
            product_id: Target product ID
            proposals: List of per-section proposal dicts
            overall_summary: Optional high-level drift assessment (informational)

        Returns:
            Dict with success, applied_count, sections_applied

        Raises:
            ResourceNotFoundError: If product not found
        """
        from giljo_mcp.services.product_service import ProductService

        update_kwargs, sections_applied = self._build_update_kwargs(proposals)

        if update_kwargs:
            product_service = ProductService(self.db_manager, self.tenant_key)
            await product_service.update_product(product_id, force=force, **update_kwargs)

        # Stamp tuning metadata
        async with self._get_session() as session:
            product = await self._get_product(session, product_id)
            current_sequence = await self._memory_repo.get_next_sequence(session, product_id, self.tenant_key) - 1
            tuning_state = product.tuning_state or {}
            tuning_state["last_tuned_at"] = datetime.now(UTC).isoformat()
            tuning_state["last_tuned_at_sequence"] = current_sequence
            product.tuning_state = validate_tuning_state(tuning_state)

            await session.commit()

        await self._emit_websocket_event(
            event_type="product:context_updated",
            data={
                "product_id": product_id,
                "applied_count": len(sections_applied),
            },
        )

        self._logger.info(
            f"Applied {len(sections_applied)} tuning updates for product {product_id}: {sections_applied}"
        )

        # Report skipped sections so agents know why their update didn't apply
        all_drift_sections = [p.get("section") for p in proposals if p.get("drift_detected")]
        skipped = [s for s in all_drift_sections if s and s not in sections_applied]

        result = {
            "success": True,
            "applied_count": len(sections_applied),
            "sections_applied": sections_applied,
        }
        if skipped:
            result["sections_skipped"] = skipped
            result["hint"] = (
                "Some sections were skipped. For structured sections like tech_stack or architecture, "
                "use sub-section keys (e.g., 'tech_stack.infrastructure', 'architecture.coding_conventions') "
                "or pass proposed_value as a dict with field names as keys."
            )
        return result

    async def check_tuning_staleness(self, product_id: str, user_id: str) -> dict[str, Any]:
        """
        Check if product context needs tuning based on completed projects since last tune.

        Args:
            product_id: Product to check
            user_id: User for notification preference lookup

        Returns:
            Dict with is_stale, projects_since_tune, threshold
        """
        async with self._get_session() as session:
            product = await self._get_product(session, product_id)

            # Get user's notification preferences
            user = await self._user_repo.get_user_by_id(session, user_id, self.tenant_key)

            prefs = (user.notification_preferences if user else None) or {}
            if not prefs.get("context_tuning_reminder", True):
                return {"is_stale": False, "projects_since_tune": 0, "threshold": 0, "enabled": False}

            threshold = max(prefs.get("tuning_reminder_threshold", 10), 3)

            # Get current sequence
            current_sequence = await self._memory_repo.get_next_sequence(session, product_id, self.tenant_key) - 1

            # Get last tuned sequence
            tuning_state = product.tuning_state or {}
            last_tuned_seq = tuning_state.get("last_tuned_at_sequence") or 0

            projects_since = max(current_sequence - last_tuned_seq, 0)

            return {
                "is_stale": projects_since >= threshold,
                "projects_since_tune": projects_since,
                "threshold": threshold,
                "enabled": True,
            }

    async def _emit_websocket_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit WebSocket event with graceful degradation."""
        if not self._websocket_manager:
            self._logger.debug(f"No WebSocket manager available for event: {event_type}")
            return

        try:
            event_data = {
                **data,
                "tenant_key": self.tenant_key,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            await self._websocket_manager.broadcast_to_tenant(
                tenant_key=self.tenant_key, event_type=event_type, data=event_data
            )
            self._logger.debug(f"WebSocket event emitted: {event_type}")
        except (RuntimeError, ValueError) as e:
            self._logger.warning(f"Failed to emit WebSocket event {event_type}: {e}", exc_info=True)
