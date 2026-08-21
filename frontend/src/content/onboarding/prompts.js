// Wording APPROVED as-is by the PM (2026-07-18, FE-9200 review closed).
// Written against the REAL update_product_context tool signature
// (api/endpoints/mcp_tools/_context_tools.py) and the product model /
// ProductForm tabs (Info / Setup / Tech / Arch / Testing).
//
// Prompt-B and Prompt-D share their back half (vision document → populated
// product card) — one library, two openings. Edition variants keyed by
// isSaasMode() per the design handoff §5: CE wording references the API-key
// connection, SaaS references browser sign-in.
//
// PROGRESSIVE FILL (design ruling): Prompt-D instructs
// section-by-section update_product_context calls in the card's own order,
// consolidated_vision STRICTLY LAST — that final write is the tutorial's
// done-signal (agentReportsDone seam in TutorialPromptScreen.vue).

import { PRODUCT_NAME } from '@/branding'

/**
 * Screen chrome for the prompt screen — copy VERBATIM from the approved mock.
 */
export const PROMPT_META = Object.freeze({
  D: Object.freeze({
    eyebrow: 'Existing codebase · one prompt',
    title: 'Let your agent read the repo and build the product card.',
    sub: 'Copy this into your MCP-connected CLI (Claude Code, Codex, Gemini). No vision document needed — the agent writes one.',
    hint: 'Paste it into your connected CLI, then watch your product card fill in on the dashboard. Come back here when your agent reports done.',
  }),
  B: Object.freeze({
    eyebrow: 'New idea · guided interview',
    title: 'Shape your idea into a vision document.',
    sub: 'Copy this into any chat tool. It interviews you, proposes where you’re unsure, and outputs a vision document you upload here.',
    hint: 'Any chat tool works — this prompt needs no MCP connection. When you have your vision document, come back and upload it.',
  }),
})

/**
 * Prompt D — "I have an existing codebase". Read-only audit, agent-written
 * vision document, then PROGRESSIVE section-by-section update_product_context
 * calls in the card's own order — the consolidated-vision write comes LAST
 * and is the tutorial's done-signal (design ruling: earlier writes only
 * update the card display, never navigate).
 *
 * @param {object} opts
 * @param {string} opts.productId - UUID of the (empty) product card to populate.
 * @param {boolean} opts.saas - SaaS edition wording toggle.
 * @returns {string}
 */
export function buildPromptD({ productId = '', saas = false } = {}) {
  const connection = saas
    ? 'You are connected to my GiljoAI workspace (browser sign-in) as an MCP server.'
    : `You are connected to my self-hosted ${PRODUCT_NAME} server (the API-key connection you were configured with).`
  return `${connection}
My product card is empty. Its product_id is "${productId}".

1. AUDIT (STRICTLY READ-ONLY): survey this repository — frontend, backend, docs, and recent git history. Do not modify, create, or delete any files during the audit.

2. VISION DOCUMENT: write a vision document in markdown (save it as VISION.md at the repository root unless one already exists) covering: what the product is and who it is for, the core value proposition, main features, current tech stack, architecture overview, quality and testing approach, and where the product is heading.

3. POPULATE MY PRODUCT CARD PROGRESSIVELY: make FIVE update_product_context calls with product_id="${productId}", one per section, in EXACTLY this order — I watch the card fill in on my screen between calls, and the FINAL call is what tells GiljoAI you are done:
   Call 1 — Info: product_name (only if the card has no name yet — the name is user-owned), product_description, core_features, and project_path (the absolute path of the repository folder you are working in — OMIT it if you have no filesystem access inside the repo, never guess).
   Call 2 — Tech: tech_stack: { programming_languages, frontend_frameworks, backend_frameworks, databases, infrastructure, target_platforms (subset of: windows, linux, macos, android, ios, web, all) }.
   Call 3 — Architecture: architecture: { architecture_pattern, design_patterns, api_style, architecture_notes, coding_conventions, brand_guidelines }.
   Call 4 — Testing & quality: quality: { quality_standards } and testing: { testing_strategy (one of: TDD, BDD, Integration-First, E2E-First, Manual, Hybrid), testing_frameworks, test_coverage_target }.
   Call 5 — STRICTLY LAST: consolidated_vision: { light: a ~150-word summary of your vision document, medium: a ~400-word summary }. Do NOT include consolidated_vision in any earlier call — this write advances my screen to the review step.
   tech_stack / architecture / quality / testing are NESTED JSON objects, not flat parameters.

4. Work in one pass — no follow-up questions unless something is genuinely blocking. After call 5 succeeds, report done; I will review and activate the product from the GiljoAI dashboard.`
}

/**
 * Prompt B — "I have an idea — help me shape it". A guided interview for ANY
 * chat tool (no MCP connection required); the output is a vision document the
 * user uploads on the tutorial's upload screen.
 *
 * @param {object} opts
 * @param {boolean} opts.saas - SaaS edition wording toggle.
 * @returns {string}
 */
export function buildPromptB({ saas = false } = {}) {
  const uploadTarget = saas
    ? `my GiljoAI workspace (${window.location.origin})`
    : 'my self-hosted GiljoAI server'
  return `Act as my product-shaping partner. Interview me ONE question at a time — never a wall of questions. Walk these areas in order (they mirror how GiljoAI's product card is organized):

1. Product info — what I am building, for whom, and what "done" looks like (a name, a description, the core features).
2. Tech stack — programming languages, frontend frameworks, backend frameworks, databases and storage, infrastructure, and target platforms.
3. Architecture — the overall pattern, key design patterns, API style, coding conventions worth locking down, and brand/design guidelines if any.
4. Quality and testing — quality standards, a testing strategy (TDD, BDD, Integration-First, E2E-First, Manual, or Hybrid), testing frameworks, and a test-coverage target.

At EVERY question offer me explicit escape hatches: "I'm not sure", "can you guide me?", and — for tech-stack and architecture choices — "would you like me to propose one?". If I hesitate, propose a sensible default and justify it in one sentence, then move on.

When we are done, write a complete vision document in markdown, organized with those same numbered sections IN THAT ORDER (the card fills section by section from it), that I can upload to ${uploadTarget}. End with a one-paragraph summary of what we decided.`
}
