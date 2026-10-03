import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({
  showToast: vi.fn(),
  updateSetupState: vi.fn(),
  removeConnection: vi.fn(),
}))

vi.mock('@/composables/useToast', () => ({ useToast: () => ({ showToast: h.showToast }) }))
vi.mock('@/services/api', () => ({
  default: {
    connect: {
      credentialStatus: vi.fn(async () => ({
        data: { has_valid_api_key: true, has_valid_oauth: true, has_expired_oauth: false, connected_harnesses: { opencode: '2026-08-25T02:00:00Z' } },
      })),
      removeConnection: h.removeConnection,
    },
  },
}))
vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    currentUser: { setup_selected_tools: ['claude_code', 'opencode'] },
    updateSetupState: h.updateSetupState,
  }),
}))
vi.mock('@/stores/websocket', () => ({ useWebSocketStore: () => ({ on: () => () => {} }) }))

import ToolsConnectDirectory from '../ToolsConnectDirectory.vue'

const stubs = {
  'v-icon': { template: '<i><slot /></i>' },
  'v-btn': { template: '<button><slot /></button>' },
  ConnectToolCard: { props: ['toolId', 'connected'], template: '<div class="stub-card" :data-tool="toolId" />' },
}

const failure = (message) =>
  Object.assign(new Error('x'), { response: { status: 500, data: { message } } })
const errorToastMentioning = (text) =>
  h.showToast.mock.calls.some(([o]) => o.type === 'error' && String(o.message).includes(text))

describe('ToolsConnectDirectory: a failed add or remove is shown and undone', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    h.updateSetupState.mockResolvedValue({})
    h.removeConnection.mockResolvedValue({ data: { removed: 1 } })
  })

  it('a failed add shows the reason and the tool is not in the fleet', async () => {
    h.updateSetupState.mockRejectedValueOnce(failure('selection not saved'))
    const wrapper = mount(ToolsConnectDirectory, { global: { stubs } })
    await flushPromises()

    await wrapper.vm.addTool('codex_cli')
    await flushPromises()

    expect(errorToastMentioning('selection not saved')).toBe(true)
    expect(wrapper.vm.fleetIds).not.toContain('codex_cli')
  })

  it('a failed remove shows the reason and the tool stays in the fleet', async () => {
    h.updateSetupState.mockRejectedValueOnce(failure('removal not saved'))
    const wrapper = mount(ToolsConnectDirectory, { global: { stubs } })
    await flushPromises()

    await wrapper.vm.removeTool('claude_code')
    await flushPromises()

    expect(errorToastMentioning('removal not saved')).toBe(true)
    expect(wrapper.vm.fleetIds).toContain('claude_code')
  })

  it('a stored connection that cannot be cleared is shown, not left to come back on reload', async () => {
    h.removeConnection.mockRejectedValueOnce(failure('connection still stored'))
    const wrapper = mount(ToolsConnectDirectory, { global: { stubs } })
    await flushPromises()

    await wrapper.vm.removeTool('opencode')
    await flushPromises()

    expect(errorToastMentioning('connection still stored')).toBe(true)
  })
})
