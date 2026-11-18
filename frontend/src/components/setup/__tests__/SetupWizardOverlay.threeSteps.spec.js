import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

let mockHarnesses = {}
let mockSurfaces = []
vi.mock('@/services/api', () => ({
  default: {
    connect: {
      credentialStatus: vi.fn(() =>
        Promise.resolve({ data: { connected_harnesses: mockHarnesses, connected_surfaces: mockSurfaces } }),
      ),
    },
  },
}))

async function mountOverlay(props = {}, { canProceed = true } = {}) {
  const SetupWizardOverlay = (await import('@/components/setup/SetupWizardOverlay.vue')).default
  const w = mount(SetupWizardOverlay, {
    props: { modelValue: true, currentStep: 1, selectedTools: ['claude_code'], ...props },
    global: {
      stubs: {
        teleport: true,
        SetupStep2Connect: {
          emits: ['can-proceed', 'step-data'],
          mounted() {
            this.$emit('can-proceed', canProceed)
            this.$emit('step-data', { connectedTools: canProceed ? ['claude_code'] : [] })
          },
          template: '<div class="step2-stub" />',
        },
        SetupStep3Commands: {
          props: ['tools'],
          template: '<div class="step3-stub" :data-tools="JSON.stringify(tools)" />',
        },
        'v-btn': { template: '<button v-bind="$attrs"><slot /></button>' },
        'v-icon': { template: '<i><slot /></i>' },
        'v-dialog': { template: '<div><slot /></div>' },
        'v-card': { template: '<div><slot /></div>' },
        'v-card-text': { template: '<div><slot /></div>' },
        'v-spacer': { template: '<span />' },
      },
    },
  })
  await flushPromises()
  return w
}

const last = (w, name) => {
  const calls = w.emitted(name)
  return calls ? calls[calls.length - 1] : undefined
}
const next = (w) => w.find('[data-testid="setup-next-btn"]')

describe('setup pop-up: exactly three steps', () => {
  it('counts three steps on every step', async () => {
    for (const [step, text] of [[0, 'Step 1 of 3'], [1, 'Step 2 of 3'], [2, 'Step 3 of 3']]) {
      const w = await mountOverlay({ currentStep: step })
      expect(w.find('.rail-count').text()).toBe(text)
    }
  })

  it('has rail nodes Choose tool, Connect it, Setup instructions and nothing else', async () => {
    const w = await mountOverlay({ currentStep: 2 })
    const labels = w.findAll('.rail-node-label').map((n) => n.text())
    expect(labels).toEqual(['Choose tool', 'Connect it', 'Setup instructions'])
    expect(w.find('[data-testid="rail-node-tools"]').exists()).toBe(true)
    expect(w.find('[data-testid="rail-node-connect"]').exists()).toBe(true)
    expect(w.find('[data-testid="rail-node-setup"]').exists()).toBe(true)
    expect(w.find('[data-testid="rail-node-launch"]').exists()).toBe(false)
    expect(w.findAll('.rail-node')).toHaveLength(3)
  })

  it('on step 3 the earlier two nodes are done and clickable, the third is active', async () => {
    const w = await mountOverlay({ currentStep: 2 })
    expect(w.find('[data-testid="rail-node-tools"]').classes()).toContain('rail-node--done')
    expect(w.find('[data-testid="rail-node-connect"]').classes()).toContain('rail-node--clickable')
    expect(w.find('[data-testid="rail-node-setup"]').classes()).toContain('rail-node--active')
  })

  it('no Launch, no restart dialog, no Install skip, no Finish button', async () => {
    for (const step of [0, 1, 2]) {
      const w = await mountOverlay({ currentStep: step })
      expect(w.find('[data-testid="install-skip"]').exists()).toBe(false)
      expect(w.find('[data-testid="setup-finish-btn"]').exists()).toBe(false)
      expect(w.text()).not.toContain('Launch')
    }
  })
})

describe('setup pop-up: Connect it goes on to Setup instructions', () => {
  it('the Connect footer button reads Next and is enabled once a tool is connected', async () => {
    const w = await mountOverlay({ currentStep: 1 })
    expect(next(w).text()).toBe('Next')
    expect(next(w).attributes('disabled')).toBeUndefined()
  })

  it('Next is disabled until a tool is connected', async () => {
    const w = await mountOverlay({ currentStep: 1 }, { canProceed: false })
    expect(next(w).attributes('disabled')).toBeDefined()
  })

  it('Next reports the step, moves to step 3 and stays open', async () => {
    const w = await mountOverlay({ currentStep: 1 })
    await next(w).trigger('click')
    const done = last(w, 'step-complete')[0]
    expect(done.step).toBe(1)
    expect(done.data.connectedTools).toEqual(['claude_code'])
    expect(last(w, 'update:currentStep')).toEqual([2])
    expect(w.emitted('update:modelValue')).toBeFalsy()
    expect(w.emitted('dismiss')).toBeFalsy()
  })

  it('"Skip for now" on Connect still reports a skip and closes the pop-up', async () => {
    const w = await mountOverlay({ currentStep: 1 }, { canProceed: false })
    await w.find('[data-testid="connect-skip"]').trigger('click')
    const done = last(w, 'step-complete')[0]
    expect(done.step).toBe(1)
    expect(done.data.skipped).toBe(true)
    expect(last(w, 'update:modelValue')).toEqual([false])
    expect(w.emitted('update:currentStep')).toBeFalsy()
  })

  it('Choose tool still goes on to Connect and stays open', async () => {
    const w = await mountOverlay({ currentStep: 0, selectedTools: ['claude_code'] })
    await next(w).trigger('click')
    expect(last(w, 'step-complete')[0].step).toBe(0)
    expect(last(w, 'update:currentStep')).toEqual([1])
    expect(w.emitted('update:modelValue')).toBeFalsy()
  })
})

describe('setup pop-up: Setup instructions and Done', () => {
  it('shows the step with the tools the person picked', async () => {
    const w = await mountOverlay({ currentStep: 2, selectedTools: ['codex_cli', 'opencode'] })
    expect(JSON.parse(w.get('.step3-stub').attributes('data-tools'))).toEqual(['codex_cli', 'opencode'])
  })

  it('the last step reads Done, is enabled with nothing set up yet, and closes the pop-up', async () => {
    const w = await mountOverlay({ currentStep: 2 }, { canProceed: false })
    expect(next(w).text()).toBe('Done')
    expect(next(w).attributes('disabled')).toBeUndefined()
    await next(w).trigger('click')
    expect(last(w, 'step-complete')[0].step).toBe(2)
    expect(last(w, 'update:modelValue')).toEqual([false])
    expect(w.emitted('dismiss')).toBeTruthy()
    expect(w.emitted('update:currentStep')).toBeFalsy()
  })

  it('has no "Skip for now" link and no second Done inside the step', async () => {
    const w = await mountOverlay({ currentStep: 2 })
    expect(w.find('[data-testid="connect-skip"]').exists()).toBe(false)
    expect(w.findAll('button').filter((b) => b.text() === 'Done')).toHaveLength(1)
  })

  it('Back goes to Connect', async () => {
    const w = await mountOverlay({ currentStep: 2 })
    await w.find('.footer-back').trigger('click')
    expect(last(w, 'update:currentStep')).toEqual([1])
  })
})

describe('Choose tool: "Connect a tool" starts empty and marks what is connected', () => {
  it('fresh: the saved picks are ignored and nothing is ticked', async () => {
    mockHarnesses = {}
    mockSurfaces = ['claude']
    const w = await mountOverlay({ currentStep: 0, selectedTools: ['claude_code'], fresh: true })
    expect(w.findAll('.tool-card--sel')).toHaveLength(0)
    expect(next(w).attributes('disabled')).toBeDefined()
  })

  it('not fresh: the saved picks are ticked as before', async () => {
    mockSurfaces = []
    const w = await mountOverlay({ currentStep: 0, selectedTools: ['claude_code'] })
    expect(w.find('[data-testid="tool-select-claude_code"]').classes()).toContain('tool-card--sel')
  })

  it('a connected tool shows a Connected mark and can still be picked', async () => {
    mockHarnesses = { 'claude-code': '2026-11-15T10:00:00Z' }
    mockSurfaces = ['claude']
    const w = await mountOverlay({ currentStep: 0, selectedTools: [], fresh: true })
    expect(w.get('[data-testid="tool-connected-claude_code"]').text()).toBe('Connected')
    expect(w.get('[data-testid="tool-connected-claude"]').text()).toBe('Connected')
    expect(w.find('[data-testid="tool-connected-opencode"]').exists()).toBe(false)
    await w.get('[data-testid="tool-select-claude_code"]').trigger('click')
    expect(w.get('[data-testid="tool-select-claude_code"]').classes()).toContain('tool-card--sel')
    expect(next(w).attributes('disabled')).toBeUndefined()
  })

  it('no connection: no marks', async () => {
    mockHarnesses = {}
    mockSurfaces = []
    const w = await mountOverlay({ currentStep: 0, selectedTools: [], fresh: true })
    expect(w.findAll('[data-testid^="tool-connected-"]')).toHaveLength(0)
  })
})
