import { getAuthCapabilities } from '@/composables/useMcpConfig'

// eslint-disable-next-line giljo-internal/no-orphaned-exports -- consumed by setupTools specs; app code reads it through setupToolsFor
export const SETUP_TOOLS = [
  {
    id: 'claude',
    name: 'Claude',
    logo: '/claude-color.svg',
    method: 'directory',
    directoryUrl: 'https://claude.ai/directory/giljo-hq',
    desktopSteps: [
      'Open Settings, then Customize',
      'Choose Discover and search for Giljo HQ',
      'Click Connect and sign in',
    ],
  },
  {
    id: 'chatgpt',
    name: 'ChatGPT',
    logo: '/icons/codex_mark_white.svg',
    method: 'directory',
    directoryUrl: 'https://chatgpt.com/plugins/plugin_asdk_app_6ad81df7a0608191a87c20051d37ffdf',
    desktopSteps: [
      'Open Settings, then Plugins',
      'Browse the directory or search for Giljo HQ',
      'Click Connect and sign in',
    ],
  },
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

export function isDirectoryTool(toolId) {
  return TOOL_META[toolId]?.method === 'directory'
}

export function setupToolsFor(isCe) {
  return isCe ? SETUP_TOOLS.filter((t) => t.method !== 'directory') : SETUP_TOOLS
}

export function sortByRegistry(toolIds) {
  const pos = (id) => {
    const i = SETUP_TOOLS.findIndex((t) => t.id === id)
    return i === -1 ? SETUP_TOOLS.length : i
  }
  return [...toolIds].sort((a, b) => pos(a) - pos(b))
}

const SURFACE_TO_TOOL_ID = {
  claude: 'claude',
  chatgpt: 'chatgpt',
}

export function toolIdForSurface(surface) {
  return SURFACE_TO_TOOL_ID[surface] ?? null
}

export function toolName(toolId) {
  return TOOL_META[toolId]?.name || 'your tool'
}

export function methodTag(toolId, isCe) {
  if (isDirectoryTool(toolId)) return 'ONE CLICK'
  if (toolId === 'generic') return 'MANUAL CONFIG'
  if (isCe) return 'API KEY'
  const caps = getAuthCapabilities(toolId)
  return caps?.supports_oauth ? 'SIGN-IN OR KEY' : 'API KEY ONLY'
}
