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
let mockSurfaces = []
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
      credentialStatus: vi.fn(() =>
        Promise.resolve({
          data: {
            has_valid_api_key: false,
            has_valid_oauth: true,
            has_expired_oauth: false,
            connected_harnesses: {},
            connected_surfaces: mockSurfaces,
          },
        }),
      ),
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
  mockSurfaces = []
})

describe('ToolsConnectDirectory: stored hosted approvals', () => {
  it('a stored Claude approval reads Configured after a reload with no live event; ChatGPT does not', async () => {
    mockSelected = ['claude', 'chatgpt']
    mockSurfaces = ['claude']
    const w = await mountDir()
    expect(w.find('[data-testid="dir-tool-claude"]').text()).toContain('Configured')
    expect(w.find('[data-testid="dir-tool-chatgpt"]').text()).not.toContain('Configured')
  })

  it('no stored approval leaves the hosted rows unconfigured', async () => {
    mockSelected = ['claude', 'chatgpt']
    const w = await mountDir()
    expect(w.find('[data-testid="dir-tool-claude"]').text()).not.toContain('Configured')
  })
})
