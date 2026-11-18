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
vi.mock('@/services/api', () => ({
  default: {
    apiKeys: { getActive: vi.fn().mockResolvedValue({ data: [] }), create: vi.fn() },
    connect: { credentialStatus: vi.fn().mockResolvedValue({ data: { connected_harnesses: {} } }) },
  },
}))
vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({
      api: { host: 'localhost', port: '7272', protocol: 'http' },
      giljo_mode: 'saas',
    }),
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

async function mountStep(selectedTools) {
  const Step = (await import('@/components/setup/SetupStep2Connect.vue')).default
  const w = mount(Step, { props: { selectedTools }, global: { stubs: globalStubs } })
  await flushPromises()
  return w
}
const fire = async (w, payload) => {
  wsHandlers['setup:tool_connected'](payload)
  await flushPromises()
}

beforeEach(() => {
  wsHandlers = {}
})

describe('SetupStep2Connect: directory tools (FE-0034b)', () => {
  it('opens on the claude tile with the "Pick the tool you work in" hero', async () => {
    const w = await mountStep(['claude_code', 'claude', 'chatgpt'])
    expect(w.find('[data-testid="connect-card-claude"]').exists()).toBe(true)
    expect(w.find('.connect-title').text()).toBe('Pick the tool you work in.')
    expect(w.find('[data-testid="directory-open-btn"]').exists()).toBe(true)
  })

  it('terminal-only selections keep their existing hero', async () => {
    const w = await mountStep(['claude_code'])
    expect(w.find('.connect-title').text()).toBe('Connect Claude Code.')
  })

  it('a hosted ChatGPT connect (surface chatgpt) flips the chatgpt tile only', async () => {
    const w = await mountStep(['claude', 'chatgpt'])
    await fire(w, { tool_name: 'generic', surface: 'chatgpt' })
    expect(w.emitted('step-data').at(-1)[0].connectedTools).toEqual(['chatgpt'])
  })

  it('a hosted Claude connect (surface claude) flips the claude tile', async () => {
    const w = await mountStep(['chatgpt', 'claude'])
    await fire(w, { tool_name: 'generic', surface: 'claude' })
    expect(w.emitted('step-data').at(-1)[0].connectedTools).toEqual(['claude'])
  })

  it('a Codex-hosted connect (no surface) does NOT flip chatgpt while chatgpt is in view', async () => {
    const w = await mountStep(['chatgpt'])
    await fire(w, { tool_name: 'generic', surface: null })
    await fire(w, { tool_name: 'generic' })
    expect(w.emitted('step-data').at(-1)[0].connectedTools).toEqual([])
    expect(w.emitted('can-proceed').at(-1)[0]).toBe(false)
  })

  it('a generic connect still flips a terminal tile in view (unchanged behaviour)', async () => {
    const w = await mountStep(['claude_code'])
    await fire(w, { tool_name: 'generic' })
    expect(w.emitted('step-data').at(-1)[0].connectedTools).toEqual(['claude_code'])
  })
})
