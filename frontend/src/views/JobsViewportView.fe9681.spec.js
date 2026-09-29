import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const h = vi.hoisted(() => ({ getActive: vi.fn(), listAgentJobs: vi.fn() }))

vi.mock('@/services/api', () => {
  const api = {
    projects: { getActive: (...a) => h.getActive(...a) },
    agentJobs: { list: (...a) => h.listAgentJobs(...a) },
    integrations: { getStatus: () => Promise.resolve({ data: {} }) },
  }
  return { api, default: api }
})
vi.mock('@/composables/useJobActions', () => ({
  useJobActions: () => ({ handleMessages: vi.fn(), handleAgentRole: vi.fn(), handleAgentJob: vi.fn(), handleStepsClick: vi.fn() }),
}))
const notify = vi.hoisted(() => ({ failure: vi.fn(), clearMissionData: vi.fn() }))
vi.mock('@/utils/notifyFailure', () => ({ notifyFailure: (...a) => notify.failure(...a) }))

import JobsViewportView from './JobsViewportView.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/jobs-overview', name: 'JobsViewport', component: { template: '<div />' } },
    { path: '/projects', name: 'Projects', component: { template: '<div />' } },
    { path: '/tools', name: 'Tools', component: { template: '<div />' } },
  ],
})

const stubs = {
  'v-tooltip': { template: `<div class="v-tooltip"><slot name="activator" :props="{}" /><slot /></div>` },
  ProjectCreateEditDialog: {
    props: ['modelValue', 'editingProject'],
    emits: ['clear-mission', 'saved', 'update:modelValue'],
    setup(_, { expose }) {
      expose({ clearMissionData: notify.clearMissionData })
    },
    template: `<div v-if="modelValue" data-testid="edit-dialog-stub">
      <button data-testid="edit-dialog-clear" @click="$emit('clear-mission')">clear</button></div>`,
  },
  BaseDialog: {
    props: ['modelValue', 'title'],
    emits: ['confirm', 'cancel', 'update:modelValue'],
    template: `<div v-if="modelValue" class="base-dialog-stub" :data-title="title">
      <slot /><button class="dialog-confirm" @click="$emit('confirm')">go</button></div>`,
  },
  CloseoutModal: { props: ['show', 'projectId'], template: '<div v-if="show" data-testid="closeout-stub">{{ projectId }}</div>' },
  DecisionModal: { props: ['show', 'orchestratorJobId'], template: '<div v-if="show" data-testid="decision-stub">{{ orchestratorJobId }}</div>' },
}

function envelope(jobs) {
  return { data: { jobs, total: jobs.length, limit: 50, offset: 0 } }
}

const DONE = {
  id: 'p-done',
  taxonomy_alias: 'BE-7',
  name: 'Finished one',
  status: 'active',
  product_id: 'prod-a',
  implementation_launched_at: '2026-08-30T22:14:00Z',
}
const DONE_AGENTS = [
  { agent_id: 'a-or', job_id: 'j-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'complete', steps: { completed: 3, total: 3 } },
  { agent_id: 'a-im', job_id: 'j-im', agent_display_name: 'implementer', status: 'complete', steps: { completed: 2, total: 2 } },
]
const RUNNING = { ...DONE, id: 'p-run', taxonomy_alias: 'BE-8', name: 'Running one' }
const RUNNING_AGENTS = [{ agent_id: 'r-or', job_id: 'rj-or', agent_name: 'orchestrator', agent_display_name: 'orchestrator', status: 'awaiting_user' }]

let pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  window.localStorage.getItem.mockImplementation((k) => (k === 'jobs.density.v2' ? 'detailed' : null))
  h.getActive.mockResolvedValue({ data: [DONE, RUNNING] })
  h.listAgentJobs.mockImplementation((pid) => Promise.resolve(envelope(pid === 'p-done' ? DONE_AGENTS : RUNNING_AGENTS)))
})

async function mountAt(query) {
  await router.push({ name: 'JobsViewport', query })
  await router.isReady()
  const wrapper = mount(JobsViewportView, { global: { plugins: [pinia, router], stubs } })
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('JobsViewportView arrivals from the retired project page (FE-9681)', () => {
  it('?project=<id> marks that card as the arrival', async () => {
    const wrapper = await mountAt({ project: 'p-run' })
    const cards = wrapper.findAll('[data-testid="jobs-board-card-wrap"]')
    const marked = cards.filter((c) => c.attributes('data-arrival') === 'true')
    expect(marked).toHaveLength(1)
    expect(marked[0].text()).toContain('Running one')
  })

  it('?project=<id> lands on the side that holds the card, even when something else is running', async () => {
    const waiting = { ...DONE, id: 'p-wait', taxonomy_alias: 'BE-9', name: 'Waiting one', implementation_launched_at: null, staging_status: null }
    h.getActive.mockResolvedValue({ data: [RUNNING, waiting] })
    h.listAgentJobs.mockImplementation((pid) => Promise.resolve(envelope(pid === 'p-run' ? RUNNING_AGENTS : [])))
    const wrapper = await mountAt({ project: 'p-wait' })
    expect(wrapper.find('[data-testid="jobs-side-staging"]').attributes('aria-pressed')).toBe('true')
    const marked = wrapper.findAll('[data-testid="jobs-board-card-wrap"]').filter((c) => c.attributes('data-arrival') === 'true')
    expect(marked).toHaveLength(1)
    expect(marked[0].text()).toContain('Waiting one')
  })

  it('?project=<id>&review=1 opens the closeout modal for that project on the board', async () => {
    const wrapper = await mountAt({ project: 'p-done', review: '1' })
    expect(wrapper.find('[data-testid="closeout-stub"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="closeout-stub"]').text()).toBe('p-done')
    expect(router.currentRoute.value.query.review).toBeUndefined()
  })

  it('?project=<id>&decide=1 opens the decision modal on that project\'s orchestrator job', async () => {
    const wrapper = await mountAt({ project: 'p-run', decide: '1' })
    expect(wrapper.find('[data-testid="decision-stub"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="decision-stub"]').text()).toBe('rj-or')
  })

  it('?project=<id>&detail=1 opens Jobs detail for that project (the old tab=jobs)', async () => {
    const wrapper = await mountAt({ project: 'p-run', detail: '1' })
    expect(wrapper.find('[data-testid="jb-detail-modal"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="jb-detail-modal"]').text()).toContain('Running one')
    expect(router.currentRoute.value.query.detail).toBeUndefined()
  })

  it('a card\'s Review control opens the closeout modal here, without leaving the board', async () => {
    const wrapper = await mountAt({})
    const done = wrapper.findAll('[data-testid="jobs-board-card-wrap"]').find((c) => c.text().includes('Finished one'))
    await done.find('[data-testid="jb-btn-review"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="closeout-stub"]').text()).toBe('p-done')
    expect(router.currentRoute.value.name).toBe('JobsViewport')
  })
})

describe('JobsViewportView hosts what the page hosted around the edit dialog and the jobs load (FE-9681 D1, D2)', () => {
  const STAGING = { ...DONE, id: 'p-stage', taxonomy_alias: 'BE-9', name: 'Waiting one', implementation_launched_at: null, staging_status: null, description: 'd', mission: 'm' }

  it('D1: Clear Mission in the board-hosted edit dialog asks, then clears through the dialog', async () => {
    h.getActive.mockResolvedValue({ data: [STAGING] })
    h.listAgentJobs.mockResolvedValue(envelope([]))
    const wrapper = await mountAt({})
    await wrapper.find('[data-testid="jb-edit-description"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="edit-dialog-stub"]').exists()).toBe(true)

    await wrapper.find('[data-testid="edit-dialog-clear"]').trigger('click')
    const confirm = wrapper.find('[data-testid="jobs-board-clear-mission-dialog"]')
    expect(confirm.exists()).toBe(true)
    expect(notify.clearMissionData).not.toHaveBeenCalled()

    await confirm.find('.dialog-confirm').trigger('click')
    expect(notify.clearMissionData).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="jobs-board-clear-mission-dialog"]').exists()).toBe(false)
  })

  it('D2: a failed agent-jobs load raises the "Agent jobs unavailable" notice instead of swallowing it', async () => {
    h.getActive.mockResolvedValue({ data: [RUNNING] })
    h.listAgentJobs.mockRejectedValue(new Error('boom'))
    await mountAt({})
    expect(notify.failure).toHaveBeenCalled()
    const [, args] = notify.failure.mock.calls[0]
    expect(args).toMatchObject({ operation: 'jobs.load', entityId: 'p-run', title: 'Agent jobs unavailable' })
  })
})
