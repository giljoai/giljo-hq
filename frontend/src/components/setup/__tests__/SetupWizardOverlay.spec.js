import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

async function mountOverlay(props = {}) {
  const SetupWizardOverlay = (await import('@/components/setup/SetupWizardOverlay.vue')).default
  return mount(SetupWizardOverlay, {
    props: { modelValue: true, mode: 'setup', currentStep: 1, ...props },
    global: {
      stubs: {
        teleport: true,
        SetupStep2Connect: { template: '<div class="step2-stub" />' },
        SetupStep3Commands: { template: '<div class="step3-stub" />' },
        SetupStep4Complete: { template: '<div class="step4-stub" />' },
        'v-btn': { template: '<button v-bind="$attrs"><slot /></button>' },
        'v-icon': { template: '<i><slot /></i>' },
        'v-dialog': { template: '<div><slot /></div>' },
        'v-card': { template: '<div><slot /></div>' },
        'v-card-text': { template: '<div><slot /></div>' },
        'v-spacer': { template: '<span />' },
      },
    },
  })
}

describe('SetupWizardOverlay — footer skip control (steps 1 & 2)', () => {
  it('renders the "Skip for now" footer link on the Connect step', async () => {
    const wrapper = await mountOverlay({ currentStep: 1 })
    const skip = wrapper.find('[data-testid="connect-skip"]')
    expect(skip.exists()).toBe(true)
    expect(skip.text()).toBe('Skip for now')
  })

  it('renders the "Skip, I\'ll do this later" footer link on the Install step', async () => {
    const wrapper = await mountOverlay({ currentStep: 2 })
    const skip = wrapper.find('[data-testid="install-skip"]')
    expect(skip.exists()).toBe(true)
    expect(skip.text()).toBe("Skip, I'll do this later")
  })

  it('does NOT render a footer skip link on Choose Tools or Launch', async () => {
    const stepTools = await mountOverlay({ currentStep: 0 })
    expect(stepTools.find('[data-testid="connect-skip"]').exists()).toBe(false)
    expect(stepTools.find('[data-testid="install-skip"]').exists()).toBe(false)

    const stepLaunch = await mountOverlay({ currentStep: 3 })
    expect(stepLaunch.find('[data-testid="connect-skip"]').exists()).toBe(false)
    expect(stepLaunch.find('[data-testid="install-skip"]').exists()).toBe(false)
  })

  it('clicking the Connect skip advances past step 1 and reports skipped', async () => {
    const wrapper = await mountOverlay({ currentStep: 1 })
    await wrapper.find('[data-testid="connect-skip"]').trigger('click')

    const stepChange = wrapper.emitted('update:currentStep')
    expect(stepChange).toBeTruthy()
    expect(stepChange[stepChange.length - 1]).toEqual([2])

    const completed = wrapper.emitted('step-complete')
    expect(completed).toBeTruthy()
    const last = completed[completed.length - 1][0]
    expect(last.step).toBe(1)
    expect(last.data.skipped).toBe(true)
    expect(last.data.connectedTools).toEqual([])
  })

  it('clicking the Install skip advances past step 2 and reports skipped', async () => {
    const wrapper = await mountOverlay({ currentStep: 2 })
    await wrapper.find('[data-testid="install-skip"]').trigger('click')

    const stepChange = wrapper.emitted('update:currentStep')
    expect(stepChange[stepChange.length - 1]).toEqual([3])

    const completed = wrapper.emitted('step-complete')
    const last = completed[completed.length - 1][0]
    expect(last.step).toBe(2)
    expect(last.data.skipped).toBe(true)
    expect(last.data.installedTools).toEqual([])
  })
})

describe('SetupWizardOverlay — Gradient Rail stepper node state', () => {
  it('marks earlier steps done, the current step active, later steps future', async () => {
    const wrapper = await mountOverlay({ currentStep: 2 })
    const tools = wrapper.find('[data-testid="rail-node-tools"]')
    const connect = wrapper.find('[data-testid="rail-node-connect"]')
    const install = wrapper.find('[data-testid="rail-node-install"]')
    const launch = wrapper.find('[data-testid="rail-node-launch"]')

    expect(tools.classes()).toContain('rail-node--done')
    expect(connect.classes()).toContain('rail-node--done')
    expect(install.classes()).toContain('rail-node--active')
    expect(launch.classes()).not.toContain('rail-node--done')
    expect(launch.classes()).not.toContain('rail-node--active')
  })

  it('only done (earlier) rail nodes are clickable', async () => {
    const wrapper = await mountOverlay({ currentStep: 2 })
    expect(wrapper.find('[data-testid="rail-node-tools"]').classes()).toContain('rail-node--clickable')
    expect(wrapper.find('[data-testid="rail-node-connect"]').classes()).toContain('rail-node--clickable')
    expect(wrapper.find('[data-testid="rail-node-install"]').classes()).not.toContain('rail-node--clickable')
    expect(wrapper.find('[data-testid="rail-node-launch"]').classes()).not.toContain('rail-node--clickable')
  })

  it('clicking a done rail node navigates back to that step', async () => {
    const wrapper = await mountOverlay({ currentStep: 2 })
    await wrapper.find('[data-testid="rail-node-tools"]').trigger('click')
    const stepChange = wrapper.emitted('update:currentStep')
    expect(stepChange[stepChange.length - 1]).toEqual([0])
  })

  it('clicking a future rail node does nothing', async () => {
    const wrapper = await mountOverlay({ currentStep: 1 })
    await wrapper.find('[data-testid="rail-node-launch"]').trigger('click')
    expect(wrapper.emitted('update:currentStep')).toBeFalsy()
  })

  it('shows the current step count out of 4', async () => {
    const wrapper = await mountOverlay({ currentStep: 2 })
    expect(wrapper.find('.rail-count').text()).toBe('Step 3 of 4')
  })
})

describe('SetupWizardOverlay — Next button gating (canProceed)', () => {
  it('disables Next on Choose Tools until a tool is selected', async () => {
    const wrapper = await mountOverlay({ currentStep: 0, selectedTools: [] })
    const next = wrapper.find('[data-testid="setup-next-btn"]')
    expect(next.attributes('disabled')).not.toBeUndefined()
  })

  it('enables Next on Choose Tools once a tool card is selected', async () => {
    const wrapper = await mountOverlay({ currentStep: 0, selectedTools: [] })
    await wrapper.find('[data-testid="tool-select-claude_code"]').trigger('click')
    const next = wrapper.find('[data-testid="setup-next-btn"]')
    expect(next.attributes('disabled')).toBeUndefined()
  })
})

describe('SetupWizardOverlay — Choose-tools grid (FE-9204 / INF-9605a: four tools)', () => {
  it('renders all four tool cards, including OpenCode and the generic client', async () => {
    const wrapper = await mountOverlay({ currentStep: 0, selectedTools: [] })
    for (const id of ['claude_code', 'codex_cli', 'opencode', 'generic']) {
      expect(wrapper.find(`[data-testid="tool-select-${id}"]`).exists()).toBe(true)
    }
  })

  it('shows a method tag per card (SaaS default: sign-in tools + manual)', async () => {
    const wrapper = await mountOverlay({ currentStep: 0, selectedTools: [] })
    expect(wrapper.find('[data-testid="tool-method-claude_code"]').text()).toBe('SIGN-IN OR KEY')
    expect(wrapper.find('[data-testid="tool-method-codex_cli"]').text()).toBe('SIGN-IN OR KEY')
    expect(wrapper.find('[data-testid="tool-method-generic"]').text()).toBe('MANUAL CONFIG')
  })

  it('toggling a card selects and deselects it (check ring)', async () => {
    const wrapper = await mountOverlay({ currentStep: 0, selectedTools: [] })
    const card = wrapper.find('[data-testid="tool-select-opencode"]')
    expect(card.classes()).not.toContain('tool-card--sel')
    await card.trigger('click')
    expect(card.classes()).toContain('tool-card--sel')
    await card.trigger('click')
    expect(card.classes()).not.toContain('tool-card--sel')
  })
})

describe('SetupWizardOverlay — Launch step (step 3) footer + rerun', () => {
  it('shows a single "Finish" button on first-time setup (no restart control)', async () => {
    const wrapper = await mountOverlay({ currentStep: 3, isRerun: false })
    expect(wrapper.find('[data-testid="setup-finish-btn"]').text()).toBe('Finish')
    expect(wrapper.find('[data-testid="setup-restart-btn"]').exists()).toBe(false)
  })

  it('shows BOTH "Restart setup" and "Done" when re-entering setup (isRerun)', async () => {
    const wrapper = await mountOverlay({ currentStep: 3, isRerun: true })
    expect(wrapper.find('[data-testid="setup-restart-btn"]').text()).toContain('Restart setup')
    expect(wrapper.find('[data-testid="setup-finish-btn"]').text()).toBe('Done')
  })

  it('clicking "Restart setup" opens the restart confirmation dialog', async () => {
    const wrapper = await mountOverlay({ currentStep: 3, isRerun: true })
    await wrapper.find('[data-testid="setup-restart-btn"]').trigger('click')
    expect(wrapper.findComponent({ name: 'VDialog' }).exists() || wrapper.find('.dlg-title').exists()).toBeTruthy()
    expect(wrapper.text()).toContain('Restart Setup')
    expect(wrapper.text()).toContain('Are you sure you want to restart?')
  })

  it('"Launch" step (step 3) content is stubbed as informational-only (no can-proceed wiring)', async () => {
    const wrapper = await mountOverlay({ currentStep: 3 })
    expect(wrapper.find('.step4-stub').exists()).toBe(true)
  })
})

describe('SetupWizardOverlay — learning mode removed (FE-9200)', () => {
  it('renders the Gradient Rail regardless of the legacy mode prop', async () => {
    const wrapper = await mountOverlay({ mode: 'learning', currentStep: 0 })
    expect(wrapper.text()).not.toContain('How to Use GiljoAI MCP')
    expect(wrapper.find('[aria-label="Setup Giljo HQ"]').exists()).toBe(true)
    expect(wrapper.find('.setup-wizard-panel').exists()).toBe(false)
    expect(wrapper.find('.wizard-rail').exists()).toBe(true)
  })
})
