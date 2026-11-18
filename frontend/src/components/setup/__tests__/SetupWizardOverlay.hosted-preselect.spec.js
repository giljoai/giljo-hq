import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('@/stores/websocket', () => ({ useWebSocketStore: () => ({ on: () => () => {} }) }))
let mockSurfaces = []
vi.mock('@/services/api', () => ({
  default: {
    connect: {
      credentialStatus: vi.fn(() => Promise.resolve({ data: { connected_harnesses: {}, connected_surfaces: mockSurfaces } })),
    },
  },
}))
vi.mock('@/services/configService', () => ({
  default: { fetchConfig: vi.fn(() => Promise.resolve({ giljo_mode: 'saas' })) },
}))

async function mountOverlay(props = {}) {
  const Overlay = (await import('@/components/setup/SetupWizardOverlay.vue')).default
  const w = mount(Overlay, {
    props: { modelValue: true, currentStep: 0, selectedTools: [], ...props },
    global: {
      stubs: {
        teleport: true,
        SetupStep2Connect: { template: '<div />' },
        'v-btn': { template: '<button v-bind="$attrs"><slot /></button>' },
        'v-icon': { template: '<i><slot /></i>' },
        'v-dialog': { template: '<div><slot /></div>' },
        'v-card': { template: '<div><slot /></div>' },
        'v-card-text': { template: '<div><slot /></div>' },
        'v-spacer': { template: '<span />' },
        Transition: { template: '<div><slot /></div>' },
      },
    },
  })
  await flushPromises()
  return w
}

beforeEach(() => {
  mockSurfaces = []
})

describe('SetupWizardOverlay Choose Tools: stored hosted approvals', () => {
  it('preselects the approved hosted apps when no choice is saved', async () => {
    mockSurfaces = ['claude', 'chatgpt']
    const w = await mountOverlay()
    expect(w.vm.$.setupState.localSelectedTools).toEqual(['claude', 'chatgpt'])
  })

  it('the person can untick a preselected app', async () => {
    mockSurfaces = ['claude']
    const w = await mountOverlay()
    w.vm.$.setupState.toggleTool('claude')
    expect(w.vm.$.setupState.localSelectedTools).toEqual([])
  })

  it('a saved choice is never overwritten', async () => {
    mockSurfaces = ['claude', 'chatgpt']
    const w = await mountOverlay({ selectedTools: ['claude_code'] })
    expect(w.vm.$.setupState.localSelectedTools).toEqual(['claude_code'])
  })

  it('nothing approved preselects nothing', async () => {
    const w = await mountOverlay()
    expect(w.vm.$.setupState.localSelectedTools).toEqual([])
  })
})
