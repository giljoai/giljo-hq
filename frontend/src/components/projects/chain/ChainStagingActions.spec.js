import { describe, it, expect, vi } from 'vitest'
import { reactive } from 'vue'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import ChainStagingActions from './ChainStagingActions.vue'

const vuetify = createVuetify()
const menuStub = { template: '<div class="menu-stub"><slot name="activator" :props="{}" /><slot /></div>' }
const tooltipStub = { template: '<div><slot name="activator" :props="{}" /><slot /></div>' }
const dialogStub = { props: ['modelValue', 'title'], template: '<div v-if="modelValue" class="dialog-stub" :data-title="title"><slot /></div>' }

function controlsFor(overrides = {}) {
  return reactive({
    chainPhase: 'ready',
    chainMode: 'subagent',
    chainStageText: 'Stage chain',
    chainStageTitle: '',
    chainStageNeedsMode: false,
    chainStaging: false,
    chainImplementReady: false,
    launching: false,
    copyingChainPrompt: false,
    deactivating: false,
    showDeactivateConfirm: false,
    showChainStopConfirm: false,
    chainStopping: false,
    patchRunMode: vi.fn(),
    handleChainStage: vi.fn(),
    handleChainImplement: vi.fn(),
    copyChainPrompt: vi.fn(),
    openDeactivateConfirm: vi.fn(),
    cancelDeactivate: vi.fn(),
    handleChainDeactivate: vi.fn(),
    openChainStopConfirm: vi.fn(),
    cancelChainStop: vi.fn(),
    handleChainStop: vi.fn(),
    ...overrides,
  })
}

function mountActions(controls, locked = false) {
  return mount(ChainStagingActions, {
    props: { chainCtx: { locked, run: { id: 'run-1' }, counter: { n: 1, m: 3 } }, controls, agentCount: 2 },
    global: { plugins: [vuetify], stubs: { 'v-menu': menuStub, 'v-tooltip': tooltipStub, BaseDialog: dialogStub } },
  })
}

const byId = (w, id) => w.find(`[data-testid="${id}"]`)

describe('ChainStagingActions (FE-9749)', () => {
  it('ready: Stage chain filled, Implement chain grey; each button reaches its writer', async () => {
    const controls = controlsFor()
    const w = mountActions(controls)
    expect(byId(w, 'stage-chain-btn').classes()).toContain('jb-btn-primary')
    expect(byId(w, 'implement-chain-btn').classes()).toContain('jb-btn-muted')
    await byId(w, 'stage-chain-btn').trigger('click')
    await byId(w, 'radio-multi-terminal').trigger('click')
    await byId(w, 'chain-group-deactivate').trigger('click')
    expect(controls.handleChainStage).toHaveBeenCalledTimes(1)
    expect(controls.patchRunMode).toHaveBeenCalledWith('multi_terminal')
    expect(controls.openDeactivateConfirm).toHaveBeenCalledTimes(1)
  })

  it('staged: Implement chain filled with the play glyph, Unstage outlined', async () => {
    const controls = controlsFor({ chainPhase: 'staged', chainStageText: 'Unstage chain', chainImplementReady: true })
    const w = mountActions(controls, true)
    const implement = byId(w, 'implement-chain-btn')
    expect(implement.classes()).toContain('jb-btn-primary')
    expect(implement.find('.v-icon').text()).toBe('mdi-play')
    expect(byId(w, 'stage-chain-btn').classes()).toContain('jb-btn-secondary')
    await implement.trigger('click')
    expect(controls.handleChainImplement).toHaveBeenCalledTimes(1)
  })

  it('staged but the goal not written yet: Implement chain stays the filled step, disabled', () => {
    const w = mountActions(controlsFor({ chainPhase: 'staged', chainImplementReady: false }), true)
    expect(byId(w, 'implement-chain-btn').classes()).toContain('jb-btn-primary')
    expect(byId(w, 'implement-chain-btn').attributes('disabled')).toBeDefined()
  })

  it('pickup: Copy chain prompt, Stop chain outlined, Deactivate chain a link', async () => {
    const controls = controlsFor({ chainPhase: 'pickup' })
    const w = mountActions(controls, true)
    await byId(w, 'sca-copy-prompt').trigger('click')
    expect(controls.copyChainPrompt).toHaveBeenCalledTimes(1)
    expect(byId(w, 'stop-chain-btn').classes()).not.toContain('csc-btn--icon')
    await byId(w, 'stop-chain-btn').trigger('click')
    expect(controls.openChainStopConfirm).toHaveBeenCalledTimes(1)
    expect(byId(w, 'chain-group-deactivate').classes()).toContain('sca-link')
  })

  it('running (FE-9793): no big buttons, no stop icon, no more-menu; the controls sit on the header row', () => {
    const controls = controlsFor({ chainPhase: 'running' })
    const w = mountActions(controls, true)
    expect(byId(w, 'staging-control-area').exists()).toBe(false)
    expect(w.findAll('.jb-btn-primary')).toHaveLength(0)
    expect(byId(w, 'stop-chain-btn').exists()).toBe(false)
    expect(byId(w, 'chain-more-menu').exists()).toBe(false)
    expect(byId(w, 'chain-compact-controls').exists()).toBe(false)
    expect(w.find('.menu-stub').exists()).toBe(false)
    expect(byId(w, 'chain-group-deactivate').exists()).toBe(false)
  })

  it('running: the Deactivate confirm still lives here, opened by the bag', () => {
    const w = mountActions(controlsFor({ chainPhase: 'running', showDeactivateConfirm: true }), true)
    const dialog = w.find('.dialog-stub[data-title="Deactivate chain?"]')
    expect(dialog.exists()).toBe(true)
    expect(dialog.text()).toContain('2 agents')
  })

  it('the Deactivate confirm names the projects and agents it resets', () => {
    const w = mountActions(controlsFor({ showDeactivateConfirm: true }))
    const dialog = w.find('.dialog-stub[data-title="Deactivate chain?"]')
    expect(dialog.text()).toContain('3 linked projects')
    expect(dialog.text()).toContain('2 agents')
  })
})
