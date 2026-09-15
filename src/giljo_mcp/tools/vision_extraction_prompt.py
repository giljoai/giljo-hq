# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


VISION_EXTRACTION_PROMPT = """You are analyzing the vision documents for a software product.
Work in TWO roles, then commit the results with update_product_context (in as many staged
calls as you need -- see HOW TO CALL).

ROLE 1 — PRODUCT MANAGER (the summaries)
Write a synthesized narrative that explains what the product is and WHY it exists: the
developer's purpose, what they are trying to achieve, important callouts, and any proposal
context worth retaining. This is a product story, not a mechanical extraction.
- vision_summaries: a list of {doc_id, light, medium} entries -- ONE per active vision
  document. doc_id is the UUID returned alongside each chunk's content by get_vision_document.
  Write to these CHARACTER budgets, not to a percentage of the source:
    light  -- about 1200 characters (a short paragraph or two)
    medium -- about 3000 characters
  These are targets, not hard limits; going somewhat over or under is fine. A long source
  document gets a summary of roughly the SAME size as a short one -- that is the point of
  a summary. Never scale the summary to the length of the input.
- consolidated_vision: a single {light, medium} dict telling the UNIFIED cross-document
  product story at the same two zoom levels:
    light  -- about 2000 characters
    medium -- about 5000 characters
  Do NOT put per-document section headers (e.g. `## filename.md`) inside the consolidated
  summary -- it is one product narrative, not a stitched concatenation. Per-document
  traceability lives elsewhere in the UI.

ROLE 2 — ENGINEERING MANAGER (the structured fields)
For tech_stack / architecture / quality / testing, write absolutes -- committed technical
decisions. EXTRACT them if the user defined them in the documents; PROPOSE sensible defaults
if the user did not (the user can modify them later). Do not leave a structured field blank
just because the document is silent on it -- propose a reasonable value instead.

FIELD RULES
- product_description: 2-3 sentences.
- testing_strategy MUST be one of: TDD, BDD, Integration-First, E2E-First, Manual, Hybrid.
- target_platforms MUST be a list from: windows, linux, macos, android, ios, web, all.
  Use 'web' for browser-based apps (SPA, PWA, responsive). Use 'all' alone if cross-platform.
- Do NOT pass product_name unless the product currently has no name -- the product name is
  user-owned.
- project_path: set it to the absolute path of the repository folder you are operating from
  (your working directory) -- this is the user's local codebase folder the orchestrator later
  uses. OMIT it entirely if you are not running with filesystem access inside the user's
  repository (never invent or guess a path). Like product_name it is user-owned -- the server
  skips it when already set.

HOW TO CALL
update_product_context is a MERGE-write and is safe to call in STAGES. Split the work
across several calls whenever one call would be large -- a single call carrying every
summary for a multi-document product can grow past what the tool transport will carry,
and that failure loses the whole call. A reasonable staging is: the card fields first,
then the per-document summaries (one call per document, or a few per call), then the
consolidated summary last.

Mark your LAST call with emit_completion=true. That re-checks the completion state and
tells the dashboard the analysis is finished, even if that final call writes nothing new.

You never have to guess whether you are done: EVERY response carries
`vision_analysis_complete` (the live flag) and `missing_for_completion` (exactly what is
still outstanding). Keep writing until `missing_for_completion` is empty. Each response
also carries `fields_skipped` -- anything that did NOT land, and why. Read it: a summary
whose doc_id matched nothing is reported there, not silently accepted.

tech_stack / architecture / quality / testing are NESTED JSON OBJECTS -- not flat
top-level parameters and not strings. Example call shape:

  update_product_context(
      product_id="<id>",
      product_description="...",
      project_path="...",
      core_features="...",
      tech_stack={"programming_languages": "...", "frontend_frameworks": "...",
                  "backend_frameworks": "...", "databases": "...",
                  "infrastructure": "...", "dev_tools": "...",
                  "target_platforms": ["web"]},
      architecture={"architecture_pattern": "...", "design_patterns": "...",
                    "api_style": "...", "architecture_notes": "...",
                    "coding_conventions": "...", "brand_guidelines": "..."},
      quality={"quality_standards": "..."},
      testing={"testing_strategy": "TDD", "testing_frameworks": "...",
               "test_coverage_target": 80},
      vision_summaries=[{"doc_id": "<uuid from get_vision_document>", "light": "...",
                         "medium": "..."}],
      consolidated_vision={"light": "...", "medium": "..."},
      emit_completion=true,
  )

A field you already wrote is protected: writing it again without force=true is reported
in `fields_skipped` rather than overwriting. Fields you have NOT yet filled always write,
so a follow-up call that completes a partially-filled card works normally.

{custom_instructions}"""
