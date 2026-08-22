/**
 * Agent Color Configuration
 *
 * Defines the visual branding for the 6 preseeded agent templates.
 * Colors match Handover 0077 specification and correspond to agent templates
 * from Handover 0041 (Agent Template Management).
 *
 */

// Canonical role color map. Keep canonical roles aligned with backend
// seeded templates: orchestrator, implementer, tester, analyzer, reviewer, documenter.
// We also support legacy aliases (implementor, researcher) via a synonym map below.
// eslint-disable-next-line giljo-internal/no-orphaned-exports -- imported by scripts/generate-agent-colors.mjs (outside src/)
export const AGENT_COLORS = {
  orchestrator: {
    hex: '#D4B08A',
    name: 'ORCHESTRATOR',
    badge: 'OR',
    description: 'Primary coordinator and mission planner',
  },
  analyzer: {
    hex: '#E07872',
    name: 'ANALYZER',
    badge: 'AN',
    description: 'Architecture and analysis tasks',
  },
  implementer: {
    hex: '#6DB3E4',
    name: 'IMPLEMENTER',
    badge: 'IM',
    description: 'Implementation and development tasks',
  },
  documenter: {
    hex: '#5EC48E',
    name: 'DOCUMENTER',
    badge: 'DO',
    description: 'Creates and updates documentation',
  },
  reviewer: {
    hex: '#AC80CC',
    name: 'REVIEWER',
    badge: 'RV',
    description: 'Code review and quality assurance',
  },
  tester: {
    hex: '#EDBA4A',
    name: 'TESTER',
    badge: 'TE',
    description: 'Testing and validation tasks',
  },
}

// Dark/light shades per role, byte-for-byte from agent-colors.scss (source of
// truth for these two shades; agentColors.js is the source of truth for hex).
// Kept separate from AGENT_COLORS so getAgentColor()'s returned object shape
// (hex, name, badge, description) never changes.
// eslint-disable-next-line giljo-internal/no-orphaned-exports -- imported by scripts/generate-agent-colors.mjs (outside src/)
export const AGENT_COLOR_SHADES = {
  orchestrator: { dark: '#b89670', light: '#e5cdb0' },
  analyzer: { dark: '#c45e58', light: '#eca09b' },
  implementer: { dark: '#4f99cc', light: '#9dcbee' },
  documenter: { dark: '#45a876', light: '#8dd8b0' },
  reviewer: { dark: '#9266b2', light: '#c8a8dd' },
  tester: { dark: '#d4a330', light: '#f3cf78' },
}

// Swatch name + WCAG contrast ratio per role, copied from the comments in
// design-tokens.scss (verified against frontend/design-system-sample-v2.html).
// Used to regenerate those comments byte-identically.
// eslint-disable-next-line giljo-internal/no-orphaned-exports -- imported by scripts/generate-agent-colors.mjs (outside src/)
export const AGENT_COLOR_META = {
  orchestrator: { swatch: 'Tan/Beige', wcagRatio: '7.48:1' },
  analyzer: { swatch: 'Coral', wcagRatio: '5.11:1' },
  implementer: { swatch: 'Sky Blue', wcagRatio: '6.64:1' },
  documenter: { swatch: 'Mint Green', wcagRatio: '7.03:1' },
  reviewer: { swatch: 'Lavender', wcagRatio: '9.08:1' },
  tester: { swatch: 'Warm Yellow', wcagRatio: '8.45:1' },
}

// Legacy/alias mapping (UI used to use these names)
const AGENT_SYNONYMS = {
  implementor: 'implementer',
  researcher: 'analyzer',
  // Common misspellings or variants
  analyser: 'analyzer',
  'code-reviewer': 'reviewer',
  'front-end-implementer': 'implementer',
  'frontend-implementer': 'implementer',
  'back-end-implementer': 'implementer',
  'backend-implementer': 'implementer',
  documentor: 'documenter',
  // Claude Code agent template mappings
  'tdd-implementor': 'implementer',
  'backend-integration-tester': 'tester',
  'frontend-tester': 'tester',
  'database-expert': 'analyzer',
  'deep-researcher': 'analyzer',
  'system-architect': 'analyzer',
  'documentation-manager': 'documenter',
  'network-security-engineer': 'reviewer',
  'ux-designer': 'implementer',
  'version-manager': 'reviewer',
  'installation-flow-agent': 'implementer',
  'orchestrator-coordinator': 'orchestrator',
}

/**
 * Get agent color by agent display name
 * @param {string} displayName - Agent display name (orchestrator, analyzer, etc.)
 * @returns {Object} Color configuration object
 */
export function getAgentColor(displayName) {
  // Normalize separators: treat underscores and spaces as hyphens so prettified
  // or specialized names all resolve identically — e.g. "implementer-backend",
  // "implementer_backend", and the title-cased "Implementer Backend" (as the
  // dashboard emits) all map to "implementer".
  const normalizedType = (displayName?.toLowerCase() || '').trim().replace(/[_\s]+/g, '-')
  // Direct match or synonym lookup
  const canonical = AGENT_SYNONYMS[normalizedType] || normalizedType
  if (AGENT_COLORS[canonical]) return AGENT_COLORS[canonical]
  // Segment match: "implementer-backend" → check "implementer", then "backend"
  const segments = normalizedType.split('-')
  for (const seg of segments) {
    const resolved = AGENT_SYNONYMS[seg] || seg
    if (AGENT_COLORS[resolved]) return AGENT_COLORS[resolved]
  }
  return AGENT_COLORS.orchestrator
}

/**
 * FE-9490: resolve the ONE colour key an agent/participant hands to
 * getAgentColor(), so every badge site agrees on which colour an agent gets.
 *
 * Before this helper, callers each picked their own priority — some tried
 * `role || display_name` (Hub participants), some `agent_name || agent_display_name`
 * (job/agent records), and one used display_name alone — so the SAME agent could
 * resolve to a different colour in the Hub than in the Agents panel whenever its
 * role/agent_name (the stable template key) differed from its human display name.
 *
 * Priority is fixed here: the stable template key (`role` or `agent_name`) wins
 * over the human-chosen display name, because the display name can carry a
 * per-session suffix (e.g. "Reviewer (Phase 5)") that a plain segment match may
 * not resolve as cleanly as the canonical key does.
 *
 * @param {string|Object|null|undefined} entity - a participant/agent object
 *   (checked for `role`, `agent_name`, `display_name`, `agent_display_name`, in
 *   that order) or a plain string, passed straight through.
 * @returns {string}
 */
export function getAgentColorKey(entity) {
  if (!entity) return ''
  if (typeof entity === 'string') return entity
  return entity.role || entity.agent_name || entity.display_name || entity.agent_display_name || ''
}

/**
 * FE-9490: derive display initials for an agent/participant name.
 *
 * Strips everything but letters/digits before splitting into words, so a
 * parenthetical or other punctuated suffix — e.g. "Reviewer (Phase 5)" — cannot
 * leak a stray character (the reported bug: initials rendered as "R("). Word
 * separators (space, hyphen, underscore, and now punctuation) all fold to the
 * same split, matching the character set getAgentColor() already normalizes.
 *
 * @param {string|null|undefined} name
 * @returns {string} Two-character initials, uppercased; '??' when nothing
 *   usable survives (empty, punctuation-only, or all-whitespace names).
 */
export function getAgentInitials(name) {
  const clean = String(name ?? '')
    .replace(/[^A-Za-z0-9]+/g, ' ')
    .trim()
  if (!clean) return '??'
  const parts = clean.split(/\s+/)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return parts[0].slice(0, 2).toUpperCase()
}
