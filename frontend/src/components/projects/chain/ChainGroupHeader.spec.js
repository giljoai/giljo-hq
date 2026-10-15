import { describe, it, expect, vi } from 'vitest'
import { reactive } from 'vue'
import { mount } from '@vue/test-utils'
import { createVuetify } from 'vuetify'
import ChainGroupHeader from './ChainGroupHeader.vue'

const vuetify = createVuetify()
const dialogStub = {
  props: ['modelValue', 'title'],
  template: '<div v-if="modelValue" class="dialog-stub" :data-title="title"><slot /></div>',
}

const chainCtx = {
  name: 'One Jobs board',
  counter: { n: 2, m: 3 },
  chainMission: '# Chain mission: One Jobs board\n\nFold chains into the board.',
  run: {
    id: 'run-1',
    resolved_order: ['p1', 'p2', 'p3'],
    project_statuses: { p1: 'completed', p2: 'implementing', p3: 'pending' },
  },
  locked: true,
}

function controlsFor(overrides = {}) {
  return reactive({
    chainPhase: 'running',
    deactivating: false,
    showChainStopConfirm: false,
    chainStopping: false,
    openChainStopConfirm: vi.fn(),
    cancelChainStop: vi.fn(),
    handleChainStop: vi.fn(),
    openDeactivateConfirm: vi.fn(),
    ...overrides,
  })
}

function mountHeader(controls, ctx = chainCtx) {
  return mount(ChainGroupHeader, {
    props: { chainCtx: ctx, controls },
    global: { plugins: [vuetify], stubs: { BaseDialog: dialogStub, EmptyState: true } },
  })
}

const byId = (w, id) => w.find(`[data-testid="${id}"]`)

describe('ChainGroupHeader running state (FE-9793)', () => {
  it('puts Stop chain and Deactivate chain on the Conductor Generated row, right-aligned', () => {
    const w = mountHeader(controlsFor())
    const tag = byId(w, 'chain-mission-tag')
    const actions = byId(w, 'chain-header-actions')
    expect(tag.exists()).toBe(true)
    expect(actions.exists()).toBe(true)
    const row = byId(w, 'chain-mission-row')
    expect(tag.element.parentElement).toBe(row.element)
    expect(row.find('[data-testid="chain-header-actions"]').exists()).toBe(true)
    expect(row.element.firstElementChild).toBe(tag.element)
    expect(row.element.lastElementChild.contains(actions.element)).toBe(true)
    expect(tag.element.compareDocumentPosition(actions.element) & 4).toBe(4)
    expect(actions.classes()).toContain('cgh-actions')

    const stop = byId(w, 'stop-chain-btn')
    expect(stop.exists()).toBe(true)
    expect(stop.text()).toContain('Stop chain')
    expect(stop.find('.v-icon').exists()).toBe(true)
    expect(stop.classes()).not.toContain('csc-btn--icon')

    const deactivate = byId(w, 'chain-group-deactivate')
    expect(deactivate.exists()).toBe(true)
    expect(deactivate.element.tagName).toBe('BUTTON')
    expect(deactivate.text()).toBe('Deactivate chain')
    expect(actions.find('[data-testid="stop-chain-btn"]').exists()).toBe(true)
    expect(actions.find('[data-testid="chain-group-deactivate"]').exists()).toBe(true)
    expect(stop.element.compareDocumentPosition(deactivate.element) & 4).toBe(4)
  })

  it('carries no stop icon and no more-menu in the running state', () => {
    const w = mountHeader(controlsFor())
    expect(byId(w, 'chain-more-menu').exists()).toBe(false)
    expect(byId(w, 'chain-compact-controls').exists()).toBe(false)
    expect(w.find('.csc-btn--icon').exists()).toBe(false)
  })

  it('Stop chain asks the bag to open the stop confirm; the confirm renders once the bag says so', async () => {
    const controls = controlsFor()
    const w = mountHeader(controls)
    await byId(w, 'stop-chain-btn').trigger('click')
    expect(controls.openChainStopConfirm).toHaveBeenCalledTimes(1)
    expect(controls.handleChainStop).not.toHaveBeenCalled()
    expect(w.find('.dialog-stub[data-title="Stop chain?"]').exists()).toBe(false)
    controls.showChainStopConfirm = true
    await w.vm.$nextTick()
    const dialog = w.find('.dialog-stub[data-title="Stop chain?"]')
    expect(dialog.exists()).toBe(true)
    expect(dialog.text()).toContain('2 becomes terminated.')
  })

  it('Deactivate chain calls the bag\'s openDeactivateConfirm and nothing else', async () => {
    const controls = controlsFor()
    const w = mountHeader(controls)
    await byId(w, 'chain-group-deactivate').trigger('click')
    expect(controls.openDeactivateConfirm).toHaveBeenCalledTimes(1)
    expect(controls.openChainStopConfirm).not.toHaveBeenCalled()
    expect(w.find('.dialog-stub[data-title="Deactivate chain?"]').exists()).toBe(false)
  })

  it('disables Deactivate chain while a deactivate is in flight', () => {
    const w = mountHeader(controlsFor({ deactivating: true }))
    expect(byId(w, 'chain-group-deactivate').attributes('disabled')).toBeDefined()
  })

  it.each(['ready', 'staged', 'pickup'])('%s: the header stays information only', (phase) => {
    const w = mountHeader(controlsFor({ chainPhase: phase }))
    expect(byId(w, 'chain-header-actions').exists()).toBe(false)
    expect(byId(w, 'stop-chain-btn').exists()).toBe(false)
    expect(byId(w, 'chain-group-deactivate').exists()).toBe(false)
    expect(byId(w, 'chain-mission-tag').exists()).toBe(true)
  })

  it('follows the phase live: the row appears when the chain starts running and leaves when it stops', async () => {
    const controls = controlsFor({ chainPhase: 'pickup' })
    const w = mountHeader(controls)
    expect(byId(w, 'chain-header-actions').exists()).toBe(false)
    controls.chainPhase = 'running'
    await w.vm.$nextTick()
    expect(byId(w, 'chain-header-actions').exists()).toBe(true)
    expect(byId(w, 'stop-chain-btn').text()).toContain('Stop chain')
    controls.chainPhase = 'staged'
    await w.vm.$nextTick()
    expect(byId(w, 'chain-header-actions').exists()).toBe(false)
    expect(byId(w, 'chain-mission-tag').exists()).toBe(true)
  })

  it('renders without a controls bag (information only)', () => {
    const w = mount(ChainGroupHeader, {
      props: { chainCtx },
      global: { plugins: [vuetify], stubs: { BaseDialog: dialogStub, EmptyState: true } },
    })
    expect(byId(w, 'chain-group-name').text()).toBe('One Jobs board')
    expect(byId(w, 'chain-header-actions').exists()).toBe(false)
  })

  it('running with no chain goal yet: the controls still render on their row', () => {
    const w = mountHeader(controlsFor(), { ...chainCtx, chainMission: '' })
    expect(byId(w, 'chain-mission-tag').exists()).toBe(false)
    expect(byId(w, 'chain-header-actions').exists()).toBe(true)
    expect(byId(w, 'stop-chain-btn').exists()).toBe(true)
  })

  it('uses design tokens only: no hex colour in the header styles', async () => {
    const source = (await import('./ChainGroupHeader.vue?raw')).default
    const style = source.slice(source.indexOf('<style'))
    expect(style).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })
})
