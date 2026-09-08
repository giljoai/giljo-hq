/**
 * JobsViewportView.launchStaged.fe9555.spec.js — FE-9555
 *
 * The board-level launch gesture: select staged projects, press "Launch staged…",
 * get one master prompt.
 *
 * Two rulings shape what is and is NOT here:
 *
 * - FE-9548 ruling: per-card Implement stays ABSENT, because a launch control on
 *   every card is one mis-click from starting the wrong project. This flow is
 *   deliberately a BOARD-level gesture with the missions in view — pinned below,
 *   since "while we're adding launch to the board, why not the card too" is the
 *   obvious wrong turn.
 * - Ruling 3: the confirm dialog is UI ergonomics, not a server gate. It must
 *   therefore behave identically whether the tenant's Headless toggle is on or
 *   off — a headless agent never sees any of this, and the fence admits it exactly
 *   as before. Pinned both ways.
 *
 * Only STAGED cards are selectable. Staged means the project finished staging and
 * has not launched — the one state where handing someone a conductor seed is the
 * correct next step. Offering it on an Implementing card would produce a prompt to
 * start work that is already running.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const h = vi.hoisted(() => ({
  getActive: vi.fn(),
  listAgentJobs: vi.fn(),
  getHeadlessLaunch: vi.fn(),
  buildMasterPrompt: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  api: {
    projects: { getActive: (...a) => h.getActive(...a) },
    agentJobs: { list: (...a) => h.listAgentJobs(...a) },
    settings: { getHeadlessLaunch: (...a) => h.getHeadlessLaunch(...a) },
    prompts: { buildMasterPrompt: (...a) => h.buildMasterPrompt(...a) },
  },
}))

vi.mock('@/composables/useJobActions', () => ({
  useJobActions: () => ({ handleMessages: vi.fn() }),
}))

import JobsViewportView from './JobsViewportView.vue'

let pinia
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/projects', name: 'Projects', component: { template: '<div />' } },
    { path: '/projects/:projectId', name: 'ProjectLaunch', component: { template: '<div />' } },
    { path: '/tools', name: 'Tools', component: { template: '<div />' } },
    { path: '/hub', name: 'Hub', component: { template: '<div />' } },
  ],
})

function envelope(jobs) {
  return { data: { jobs, total: jobs.length, limit: 50, offset: 0 } }
}

const tooltipStub = {
  template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>`,
}

// staging_status 'staging_complete' + never launched === Staged (jobsSectionLabel.js).
const STAGED_A = {
  id: 'stg-a',
  taxonomy_alias: 'FE-0001',
  name: 'First staged thing',
  status: 'active',
  staging_status: 'staging_complete',
  implementation_launched_at: null,
}
const STAGED_B = {
  id: 'stg-b',
  taxonomy_alias: 'BE-0002',
  name: 'Second staged thing',
  status: 'active',
  staging_status: 'staging_complete',
  implementation_launched_at: null,
}
// Already launched === Implementing, so never selectable.
const IMPLEMENTING = {
  id: 'imp-1',
  taxonomy_alias: 'IN-0003',
  name: 'Already running',
  status: 'active',
  staging_status: 'staging_complete',
  implementation_launched_at: '2026-09-01T10:00:00Z',
}

function mountView() {
  return mount(JobsViewportView, {
    global: { plugins: [pinia, router], stubs: { 'v-tooltip': tooltipStub } },
  })
}

async function mountWith(projects, { headless = true } = {}) {
  h.getActive.mockResolvedValue({ data: projects })
  h.getHeadlessLaunch.mockResolvedValue({ data: { allow_headless_launch: headless } })
  const wrapper = mountView()
  await flushPromises()
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  h.listAgentJobs.mockResolvedValue(envelope([]))
  h.getHeadlessLaunch.mockResolvedValue({ data: { allow_headless_launch: true } })
  h.buildMasterPrompt.mockResolvedValue({
    data: { prompt: 'MASTER PROMPT', execution_mode: 'subagent', projects: [] },
  })
})

describe('JobsViewportView — board-level Launch staged (FE-9555)', () => {
  it('offers a selection checkbox on a staged card', async () => {
    const wrapper = await mountWith([STAGED_A])

    expect(wrapper.find('[data-testid="jb-select-stg-a"]').exists()).toBe(true)
  })

  it('does not offer one on a project that is already implementing', async () => {
    const wrapper = await mountWith([IMPLEMENTING])

    expect(wrapper.find('[data-testid="jb-select-imp-1"]').exists()).toBe(false)
  })

  it('keeps the launch bar hidden until something is selected', async () => {
    const wrapper = await mountWith([STAGED_A, STAGED_B])

    expect(wrapper.find('[data-testid="jobs-launch-bar"]').exists()).toBe(false)
  })

  it('shows the launch bar with a count once projects are selected', async () => {
    const wrapper = await mountWith([STAGED_A, STAGED_B])

    await wrapper.find('[data-testid="jb-select-stg-a"]').trigger('click')
    await wrapper.find('[data-testid="jb-select-stg-b"]').trigger('click')

    const bar = wrapper.find('[data-testid="jobs-launch-bar"]')
    expect(bar.exists()).toBe(true)
    expect(bar.text()).toContain('2')
  })

  it('deselecting the last project puts the launch bar away again', async () => {
    const wrapper = await mountWith([STAGED_A])

    await wrapper.find('[data-testid="jb-select-stg-a"]').trigger('click')
    expect(wrapper.find('[data-testid="jobs-launch-bar"]').exists()).toBe(true)

    await wrapper.find('[data-testid="jb-select-stg-a"]').trigger('click')
    expect(wrapper.find('[data-testid="jobs-launch-bar"]').exists()).toBe(false)
  })

  it('opens the confirm dialog with exactly the selected projects, in selection order', async () => {
    const wrapper = await mountWith([STAGED_A, STAGED_B])

    await wrapper.find('[data-testid="jb-select-stg-b"]').trigger('click')
    await wrapper.find('[data-testid="jb-select-stg-a"]').trigger('click')
    await wrapper.find('[data-testid="jobs-launch-open"]').trigger('click')

    expect(wrapper.vm.launchDialogOpen).toBe(true)
    expect(wrapper.vm.selectedProjects.map((p) => p.id)).toEqual(['stg-b', 'stg-a'])
  })

  it('launches nothing by itself -- opening the dialog calls no project API', async () => {
    /** Ruling 4: the UI door prepares prompts and crosses gates; it never runs. */
    const wrapper = await mountWith([STAGED_A])

    await wrapper.find('[data-testid="jb-select-stg-a"]').trigger('click')
    await wrapper.find('[data-testid="jobs-launch-open"]').trigger('click')

    expect(h.buildMasterPrompt).not.toHaveBeenCalled() // not until a mode is chosen
  })

  it('behaves identically with the Headless toggle OFF', async () => {
    /** Ruling 3: the dialog is ergonomics, not a gate. Coupling it to the toggle
     * would make a security setting silently control navigation. */
    const wrapper = await mountWith([STAGED_A], { headless: false })

    await wrapper.find('[data-testid="jb-select-stg-a"]').trigger('click')

    expect(wrapper.find('[data-testid="jobs-launch-bar"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="jobs-launch-open"]').exists()).toBe(true)
  })

  it('still has NO per-card Implement button (FE-9548 ruling holds)', async () => {
    const wrapper = await mountWith([STAGED_A, STAGED_B])

    // `jobs-board-card-wrap` (the component root), not `jobs-board-card` (the
    // inner v-card, which the global stub does not render) -- the first selector
    // tried matched nothing, and the loop below would have passed vacuously
    // without the length assertion guarding it.
    const cards = wrapper.findAll('[data-testid="jobs-board-card-wrap"]')
    expect(cards.length).toBeGreaterThan(0)
    for (const card of cards) {
      expect(card.text()).not.toMatch(/\bImplement\b/)
    }
  })

  it('drops a project from the selection when it leaves the board', async () => {
    /**
     * A staged project that gets launched elsewhere stops being staged, and its
     * card goes. Without pruning, the stale id stays selected and the launch bar
     * counts a project the user can no longer see -- and the master prompt would
     * be built for it.
     */
    const wrapper = await mountWith([STAGED_A, STAGED_B])
    await wrapper.find('[data-testid="jb-select-stg-a"]').trigger('click')
    await wrapper.find('[data-testid="jb-select-stg-b"]').trigger('click')
    expect(wrapper.vm.selectedProjects).toHaveLength(2)

    h.getActive.mockResolvedValue({ data: [STAGED_B] })
    await wrapper.vm.fetchBoard()
    await flushPromises()

    expect(wrapper.vm.selectedProjects.map((p) => p.id)).toEqual(['stg-b'])
  })
})
