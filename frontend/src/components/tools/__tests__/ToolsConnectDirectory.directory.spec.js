import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

let wsHandlers = {}
vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    on: (event, handler) => {
      wsHandlers[event] = handler
      return () => {}
    },
  }),
}))
let mockSelected = []
vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    currentUser: { setup_selected_tools: mockSelected },
    updateSetupState: vi.fn().mockResolvedValue({}),
  }),
}))
vi.mock('@/services/api', () => ({
  default: {
    apiKeys: { getActive: vi.fn().mockResolvedValue({ data: [] }), create: vi.fn() },
    connect: {
      credentialStatus: vi.fn().mockResolvedValue({
        data: { has_valid_api_key: false, has_valid_oauth: false, has_expired_oauth: false, connected_harnesses: {} },
      }),
      removeConnection: vi.fn(),
    },
  },
}))
let mockMode = 'saas'
vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockImplementation(() =>
      Promise.resolve({ api: { host: 'localhost', port: '7272', protocol: 'http' }, giljo_mode: mockMode }),
    ),
  },
}))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: vi.fn() }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

const globalStubs = {
  'v-text-field': { template: '<input />', props: ['modelValue'] },
  'v-icon': { template: '<i><slot /></i>' },
  'v-btn': { template: '<button><slot /></button>' },
  'v-progress-circular': { template: '<span />' },
  'v-alert': { template: '<div><slot /></div>' },
  'v-expand-transition': { template: '<div><slot /></div>' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
}

async function mountDir() {
  const Dir = (await import('@/components/tools/ToolsConnectDirectory.vue')).default
  const w = mount(Dir, { global: { stubs: globalStubs } })
  await flushPromises()
  return w
}

beforeEach(() => {
  wsHandlers = {}
  mockMode = 'saas'
  mockSelected = []
})

describe('ToolsConnectDirectory: directory tiles (FE-0034b)', () => {
  it('the picker lists Claude and ChatGPT first in SaaS', async () => {
    const w = await mountDir()
    const ids = w.findAll('[data-testid^="dir-pick-"]').map((n) => n.attributes('data-testid'))
    expect(ids).toEqual([
      'dir-pick-claude',
      'dir-pick-chatgpt',
      'dir-pick-claude_code',
      'dir-pick-codex_cli',
      'dir-pick-opencode',
      'dir-pick-generic',
    ])
  })

  it('CE hides the two directory tiles from the picker', async () => {
    mockMode = 'ce'
    const w = await mountDir()
    const ids = w.findAll('[data-testid^="dir-pick-"]').map((n) => n.attributes('data-testid'))
    expect(ids).toEqual(['dir-pick-claude_code', 'dir-pick-codex_cli', 'dir-pick-opencode', 'dir-pick-generic'])
  })

  it('the rail orders directory tools before terminal tools whatever the stored order', async () => {
    mockSelected = ['claude_code', 'chatgpt', 'claude']
    const w = await mountDir()
    const ids = w.findAll('[data-testid^="dir-tool-"]').map((n) => n.attributes('data-testid'))
    expect(ids).toEqual(['dir-tool-claude', 'dir-tool-chatgpt', 'dir-tool-claude_code'])
  })

  it('a hosted ChatGPT connect turns the chatgpt row Configured; Codex-hosted does not', async () => {
    mockSelected = ['claude', 'chatgpt']
    const w = await mountDir()
    const row = () => w.find('[data-testid="dir-tool-chatgpt"]').text()
    await wsHandlers['setup:tool_connected']({ tool_name: 'generic', surface: null })
    await flushPromises()
    expect(row()).not.toContain('Configured')
    await wsHandlers['setup:tool_connected']({ tool_name: 'generic', surface: 'chatgpt' })
    await flushPromises()
    expect(row()).toContain('Configured')
    expect(w.find('[data-testid="dir-tool-claude"]').text()).not.toContain('Configured')
  })
})
