import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({ on: () => () => {} }),
}))
let mockStatus = {}
vi.mock('@/services/api', () => ({
  default: {
    apiKeys: { getActive: vi.fn().mockResolvedValue({ data: [] }), create: vi.fn() },
    connect: { credentialStatus: vi.fn(() => Promise.resolve({ data: mockStatus })) },
  },
}))
vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({ api: { host: 'localhost', port: '7272', protocol: 'http' }, giljo_mode: 'saas' }),
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

beforeEach(() => {
  mockStatus = {}
})

describe('SetupStep2Connect: a stored hosted-app approval', () => {
  it('a stored Claude approval reads connected with no live event and enables Next', async () => {
    mockStatus = { connected_harnesses: {}, connected_surfaces: ['claude'] }
    const w = await mountStep(['claude', 'chatgpt'])
    expect(w.emitted('step-data').at(-1)[0].connectedTools).toEqual(['claude'])
    expect(w.emitted('can-proceed').at(-1)[0]).toBe(true)
  })

  it('a stored ChatGPT approval lights only the chatgpt tile', async () => {
    mockStatus = { connected_harnesses: {}, connected_surfaces: ['chatgpt'] }
    const w = await mountStep(['claude', 'chatgpt'])
    expect(w.emitted('step-data').at(-1)[0].connectedTools).toEqual(['chatgpt'])
  })

  it('a surface whose tile is not in the chosen tools lights nothing', async () => {
    mockStatus = { connected_harnesses: {}, connected_surfaces: ['claude'] }
    const w = await mountStep(['claude_code'])
    expect(w.emitted('step-data').at(-1)[0].connectedTools).toEqual([])
    expect(w.emitted('can-proceed').at(-1)[0]).toBe(false)
  })

  it('PIN: a local CLI tool with an OLD stored record is never green, even beside a stored hosted approval', async () => {
    mockStatus = { connected_harnesses: { 'claude-code': '2020-01-01T00:00:00Z' }, connected_surfaces: ['claude'] }
    const w = await mountStep(['claude_code'])
    expect(w.find('[data-testid="hero-check"]').exists()).toBe(false)
    expect(w.find('[data-testid="connect-card-claude_code"]').attributes('data-state')).toBe('connected_before')
    expect(w.emitted('can-proceed').at(-1)[0]).toBe(true)
  })
})
