
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

// eslint-disable-next-line giljo-internal/no-orphaned-exports -- imported by scripts/generate-agent-colors.mjs (outside src/)
export const AGENT_COLOR_SHADES = {
  orchestrator: { dark: '#b89670', light: '#e5cdb0' },
  analyzer: { dark: '#c45e58', light: '#eca09b' },
  implementer: { dark: '#4f99cc', light: '#9dcbee' },
  documenter: { dark: '#45a876', light: '#8dd8b0' },
  reviewer: { dark: '#9266b2', light: '#c8a8dd' },
  tester: { dark: '#d4a330', light: '#f3cf78' },
}

// eslint-disable-next-line giljo-internal/no-orphaned-exports -- imported by scripts/generate-agent-colors.mjs (outside src/)
export const AGENT_COLOR_META = {
  orchestrator: { swatch: 'Tan/Beige', wcagRatio: '7.48:1' },
  analyzer: { swatch: 'Coral', wcagRatio: '5.11:1' },
  implementer: { swatch: 'Sky Blue', wcagRatio: '6.64:1' },
  documenter: { swatch: 'Mint Green', wcagRatio: '7.03:1' },
  reviewer: { swatch: 'Lavender', wcagRatio: '9.08:1' },
  tester: { swatch: 'Warm Yellow', wcagRatio: '8.45:1' },
}

const AGENT_SYNONYMS = {
  implementor: 'implementer',
  researcher: 'analyzer',
  analyser: 'analyzer',
  'code-reviewer': 'reviewer',
  'front-end-implementer': 'implementer',
  'frontend-implementer': 'implementer',
  'back-end-implementer': 'implementer',
  'backend-implementer': 'implementer',
  documentor: 'documenter',
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

export function getAgentColor(displayName) {
  const normalizedType = (displayName?.toLowerCase() || '').trim().replace(/[_\s]+/g, '-')
  const canonical = AGENT_SYNONYMS[normalizedType] || normalizedType
  if (AGENT_COLORS[canonical]) return AGENT_COLORS[canonical]
  const segments = normalizedType.split('-')
  for (const seg of segments) {
    const resolved = AGENT_SYNONYMS[seg] || seg
    if (AGENT_COLORS[resolved]) return AGENT_COLORS[resolved]
  }
  return AGENT_COLORS.orchestrator
}

export function getAgentColorKey(entity) {
  if (!entity) return ''
  if (typeof entity === 'string') return entity
  return entity.role || entity.agent_name || entity.display_name || entity.agent_display_name || ''
}

export function getAgentInitials(name) {
  const clean = String(name ?? '')
    .replace(/[^A-Za-z0-9]+/g, ' ')
    .trim()
  if (!clean) return '??'
  const parts = clean.split(/\s+/)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return parts[0].slice(0, 2).toUpperCase()
}
