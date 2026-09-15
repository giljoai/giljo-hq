import { getAuthCapabilities } from '@/composables/useMcpConfig'

export const SETUP_TOOLS = [
  { id: 'claude_code', name: 'Claude Code', logo: '/claude-color.svg' },
  { id: 'codex_cli', name: 'Codex CLI', logo: '/icons/codex_mark_white.svg' },
  { id: 'opencode', name: 'OpenCode', logo: '/opencode-mark-white.svg' },
  { id: 'generic', name: 'Generic MCP client', logo: '/logo-mcp.svg' },
]

const HARNESS_TO_TOOL_ID = {
  'claude-code': 'claude_code',
  codex: 'codex_cli',
  opencode: 'opencode',
  generic: 'generic',
}

export function toolIdForHarness(harness) {
  return HARNESS_TO_TOOL_ID[harness] ?? null
}

const TOOL_ID_TO_HARNESS = Object.fromEntries(
  Object.entries(HARNESS_TO_TOOL_ID).map(([harness, toolId]) => [toolId, harness]),
)

export function harnessForToolId(toolId) {
  return TOOL_ID_TO_HARNESS[toolId] ?? null
}

export const TOOL_META = Object.fromEntries(SETUP_TOOLS.map((t) => [t.id, t]))

export function toolName(toolId) {
  return TOOL_META[toolId]?.name || 'your tool'
}

export function methodTag(toolId, isCe) {
  if (toolId === 'generic') return 'MANUAL CONFIG'
  if (isCe) return 'API KEY'
  const caps = getAuthCapabilities(toolId)
  return caps?.supports_oauth ? 'SIGN-IN OR KEY' : 'API KEY ONLY'
}
