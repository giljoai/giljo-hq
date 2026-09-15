import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'

let wsHandlers = {}
vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    on: (event, handler) => {
      wsHandlers[event] = handler
      return () => {}
    },
  }),
}))

let mockSelectedTools = ['claude_code', 'codex_cli']
const updateSetupState = vi.fn().mockResolvedValue({})
vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    currentUser: { setup_selected_tools: mockSelectedTools },
    updateSetupState,
  }),
}))

const mockCredentialStatus = vi.fn()
vi.mock('@/services/api', () => ({
  default: {
    apiKeys: {
      getActive: vi.fn().mockResolvedValue({ data: [] }),
      create: vi.fn().mockResolvedValue({ data: { api_key: 'gk_test' } }),
    },
    connect: {
      credentialStatus: (...a) => mockCredentialStatus(...a),
    },
  },
}))
vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({
      api: { host: 'localhost', port: '7272', protocol: 'http', ssl_enabled: false },
      giljo_mode: 'saas',
    }),
  },
}))
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: vi.fn().mockResolvedValue(true) }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: vi.fn() }) }))

const globalStubs = {
  'v-text-field': { template: '<input class="v-text-field-stub" />', props: ['modelValue'] },
  'v-icon': { template: '<i class="v-icon-stub"><slot /></i>' },
  'v-btn': { template: '<button class="v-btn-stub" @click="$emit(\'click\', $event)"><slot /></button>', emits: ['click'] },
  'v-progress-circular': { template: '<span />' },
  'v-alert': { template: '<div><slot /></div>' },
  'v-expand-transition': { template: '<div><slot /></div>' },
  'v-tooltip': { template: '<div><slot name="activator" :props="{}" /><slot /></div>' },
}

const NO_CREDS = { has_valid_api_key: false, has_valid_oauth: false, has_expired_oauth: false }
const VALID_KEY = { has_valid_api_key: true, has_valid_oauth: false, has_expired_oauth: false }
const EXPIRED_OAUTH = { has_valid_api_key: false, has_valid_oauth: false, has_expired_oauth: true }
const KEY_AND_CLAUDE_CONNECTED = {
  ...VALID_KEY,
  connected_harnesses: { 'claude-code': '2026-08-25T02:00:00Z' },
}

let mountedWrappers = []
async function mountDir() {
  const ToolsConnectDirectory = (await import('@/components/tools/ToolsConnectDirectory.vue')).default
  const wrapper = mount(ToolsConnectDirectory, { global: { stubs: globalStubs } })
  mountedWrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  wsHandlers = {}
  mockSelectedTools = ['claude_code', 'codex_cli']
  updateSetupState.mockClear()
  mockCredentialStatus.mockReset()
  mockCredentialStatus.mockResolvedValue({ data: { ...NO_CREDS } })
})

afterEach(() => {
  mountedWrappers.forEach((w) => w.unmount())
  mountedWrappers = []
})

describe('ToolsConnectDirectory (C2, FE-9204)', () => {
  it('lists the fleet from setup_selected_tools with a + Add a tool row', async () => {
    const wrapper = await mountDir()
    expect(wrapper.find('[data-testid="dir-tool-claude_code"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="dir-tool-codex_cli"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="dir-add-tool"]').exists()).toBe(true)
  })

  it('selecting a tool shows its shared connect card in the action window', async () => {
    const wrapper = await mountDir()
    await wrapper.find('[data-testid="dir-tool-codex_cli"]').trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="connect-card-codex_cli"]').exists()).toBe(true)
  })

  it('+ Add a tool opens the six-tool picker in the action window', async () => {
    const wrapper = await mountDir()
    await wrapper.find('[data-testid="dir-add-tool"]').trigger('click')
    await nextTick()
    for (const id of ['claude_code', 'opencode', 'generic']) {
      expect(wrapper.find(`[data-testid="dir-pick-${id}"]`).exists()).toBe(true)
    }
  })

  it('picking a new tool adds it to the fleet and persists the selection', async () => {
    const wrapper = await mountDir()
    await wrapper.find('[data-testid="dir-add-tool"]').trigger('click')
    await nextTick()
    await wrapper.find('[data-testid="dir-pick-opencode"]').trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="dir-tool-opencode"]').exists()).toBe(true)
    expect(updateSetupState).toHaveBeenCalledWith(
      expect.objectContaining({ setup_selected_tools: expect.arrayContaining(['opencode']) }),
    )
    expect(wrapper.find('[data-testid="connect-card-opencode"]').exists()).toBe(true)
  })

  it('removing a tool drops it from the fleet and persists', async () => {
    const wrapper = await mountDir()
    await wrapper.find('[data-testid="dir-remove-tool"]').trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="dir-tool-claude_code"]').exists()).toBe(false)
    expect(updateSetupState).toHaveBeenCalledWith(
      expect.objectContaining({ setup_selected_tools: expect.not.arrayContaining(['claude_code']) }),
    )
  })
})

describe('ToolsConnectDirectory — FE-9274 durable Configured state', () => {
  it('fetches credential-status on mount and renders idle ("Not set up") when nothing is valid', async () => {
    const wrapper = await mountDir()
    expect(mockCredentialStatus).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="dir-tool-claude_code"] .dir-rail-dot--configured').exists()).toBe(false)
    expect(wrapper.find('[data-testid="dir-tool-codex_cli"]').text()).toContain('Not set up')
  })

  it('a valid API key alone configures NO row — a credential is not a connection', async () => {
    mockCredentialStatus.mockResolvedValue({ data: { ...VALID_KEY } })
    const wrapper = await mountDir()
    expect(wrapper.find('[data-testid="dir-tool-claude_code"] .dir-rail-dot--configured').exists()).toBe(false)
    expect(wrapper.find('[data-testid="dir-tool-codex_cli"] .dir-rail-dot--configured').exists()).toBe(false)
  })

  it('only the tool that completed a handshake renders Configured', async () => {
    mockCredentialStatus.mockResolvedValue({ data: { ...KEY_AND_CLAUDE_CONNECTED } })
    const wrapper = await mountDir()
    expect(wrapper.find('[data-testid="dir-tool-claude_code"] .dir-rail-dot--configured').exists()).toBe(true)
    expect(wrapper.find('[data-testid="dir-tool-claude_code"]').text()).toContain('Configured')
    expect(wrapper.find('[data-testid="dir-tool-codex_cli"] .dir-rail-dot--configured').exists()).toBe(false)
  })

  it('renders the amber "Requires re-authentication" state when OAuth expired and no valid key covers it', async () => {
    mockCredentialStatus.mockResolvedValue({ data: { ...EXPIRED_OAUTH } })
    const wrapper = await mountDir()
    expect(wrapper.find('[data-testid="dir-tool-claude_code"] .dir-rail-dot--reauth').exists()).toBe(true)
    expect(wrapper.find('[data-testid="dir-tool-claude_code"]').text()).toContain('Requires re-authentication')
  })

  it('CORE BUG FIX: status survives unmount + remount (navigate away and back) instead of reverting to waiting', async () => {
    mockCredentialStatus.mockResolvedValue({ data: { ...KEY_AND_CLAUDE_CONNECTED } })
    const wrapper = await mountDir()
    expect(wrapper.find('[data-testid="dir-tool-claude_code"]').text()).toContain('Configured')

    wrapper.unmount()

    const wrapper2 = await mountDir()
    expect(mockCredentialStatus).toHaveBeenCalledTimes(2)
    expect(wrapper2.find('[data-testid="dir-tool-claude_code"]').text()).toContain('Configured')
    expect(wrapper2.find('[data-testid="dir-tool-claude_code"] .dir-rail-dot--configured').exists()).toBe(true)
  })

  it('refetches on the setup:tool_connected WS event and flips only the connected tool', async () => {
    const wrapper = await mountDir()
    expect(wrapper.find('[data-testid="dir-tool-codex_cli"]').text()).toContain('Not set up')

    mockCredentialStatus.mockResolvedValue({ data: { ...KEY_AND_CLAUDE_CONNECTED } })
    wsHandlers['setup:tool_connected']({ tool_name: 'mcp_connected' })
    await flushPromises()

    expect(mockCredentialStatus).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-testid="dir-tool-claude_code"]').text()).toContain('Configured')
    expect(wrapper.find('[data-testid="dir-tool-codex_cli"]').text()).not.toContain('Configured')
  })

  it('refetches on a REAL resolved-harness payload, not just the retired mcp_connected literal', async () => {
    const wrapper = await mountDir()
    expect(wrapper.find('[data-testid="dir-tool-codex_cli"]').text()).toContain('Not set up')

    mockCredentialStatus.mockResolvedValue({ data: { ...KEY_AND_CLAUDE_CONNECTED } })
    wsHandlers['setup:tool_connected']({ tool_name: 'claude-code' })
    await flushPromises()

    expect(mockCredentialStatus).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-testid="dir-tool-claude_code"]').text()).toContain('Configured')
  })

  it('refetches on the api-key-created window event', async () => {
    const wrapper = await mountDir()
    mockCredentialStatus.mockResolvedValue({ data: { ...KEY_AND_CLAUDE_CONNECTED } })

    window.dispatchEvent(new Event('api-key-created'))
    await flushPromises()

    expect(mockCredentialStatus).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-testid="dir-tool-claude_code"]').text()).toContain('Configured')
  })

  it('an api-key-revoked event that leaves no valid credential shows "API key deleted" (in-session only)', async () => {
    mockCredentialStatus.mockResolvedValue({ data: { ...KEY_AND_CLAUDE_CONNECTED } })
    const wrapper = await mountDir()
    expect(wrapper.find('[data-testid="dir-tool-claude_code"]').text()).toContain('Configured')

    mockCredentialStatus.mockResolvedValue({ data: { ...NO_CREDS } })
    window.dispatchEvent(new Event('api-key-revoked'))
    await flushPromises()

    expect(wrapper.find('[data-testid="dir-tool-claude_code"]').text()).toContain('API key deleted')

    const wrapper2 = await mountDir()
    expect(wrapper2.find('[data-testid="dir-tool-codex_cli"]').text()).toContain('Not set up')
    expect(wrapper2.find('[data-testid="dir-tool-claude_code"]').text()).not.toContain('API key deleted')
  })

  it('an api-key-revoked event that STILL leaves a valid credential does not show "API key deleted"', async () => {
    mockCredentialStatus.mockResolvedValue({ data: { ...KEY_AND_CLAUDE_CONNECTED } })
    const wrapper = await mountDir()

    window.dispatchEvent(new Event('api-key-revoked'))
    await flushPromises()

    expect(wrapper.find('[data-testid="dir-tool-claude_code"]').text()).toContain('Configured')
    expect(wrapper.find('[data-testid="dir-tool-claude_code"]').text()).not.toContain('API key deleted')
  })

  it('"I already configured this" optimistically shows Configured ahead of the next durable fetch', async () => {
    const wrapper = await mountDir()
    await wrapper.find('[data-testid="already-configured"]').trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="dir-tool-claude_code"]').text()).toContain('Configured')
  })

  it('BUG (auditor-found): a later authoritative fetch supersedes a stale optimistic "Configured" click', async () => {
    const wrapper = await mountDir()
    await wrapper.find('[data-testid="already-configured"]').trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="dir-tool-claude_code"]').text()).toContain('Configured')

    mockCredentialStatus.mockResolvedValue({ data: { ...NO_CREDS } })
    window.dispatchEvent(new Event('api-key-revoked'))
    await flushPromises()

    expect(wrapper.find('[data-testid="dir-tool-claude_code"]').text()).not.toContain('Configured')
    expect(wrapper.find('[data-testid="dir-tool-claude_code"]').text()).toContain('API key deleted')
  })
})
