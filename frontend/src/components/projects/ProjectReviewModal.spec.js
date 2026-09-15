
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import ProjectReviewModal from '@/components/projects/ProjectReviewModal.vue'
import { useProjectStateStore } from '@/stores/projectStateStore'
import api from '@/services/api'

const vuetify = createVuetify()

const hubRouter = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/hub', name: 'Hub', component: { template: '<div />' } },
  ],
})


const PROJECT_ID = 'proj-fe6021'

function makeReviewResponse(executionModeOverride = 'multi_terminal') {
  return {
    data: {
      project: {
        id: PROJECT_ID,
        project_id: PROJECT_ID,
        name: 'FE-6021 Test Project',
        execution_mode: executionModeOverride,
        status: 'active',
        agents: [],
      },
      agent_jobs: [],
      memory_entries: [],
    },
  }
}


async function mountModal() {
  const pinia = createPinia()
  setActivePinia(pinia)

  const wrapper = mount(ProjectReviewModal, {
    props: {
      show: false,
      projectId: PROJECT_ID,
    },
    global: {
      plugins: [pinia, vuetify, hubRouter],
    },
  })

  const projectStateStore = useProjectStateStore()
  projectStateStore.setProject({
    id: PROJECT_ID,
    project_id: PROJECT_ID,
    execution_mode: 'subagent',
  })

  await wrapper.setProps({ show: true })
  await flushPromises()

  return { wrapper, projectStateStore }
}


describe('ProjectReviewModal.vue — execution_mode store-first (FE-6021)', () => {
  beforeEach(() => {
    api.projects.review = vi.fn().mockResolvedValue(makeReviewResponse('multi_terminal'))
    api.threads = {
      list: vi.fn().mockResolvedValue({ data: { threads: [] } }),
      history: vi.fn().mockResolvedValue({ data: { thread: null, messages: [] } }),
      create: vi.fn(),
    }
  })

  it('executionModeLabel resolves from store, not stale REST snapshot', async () => {
    const { wrapper } = await mountModal()

    expect(wrapper.vm.executionModeLabel).toBe('Subagent')
  })

  it('executionModeIcon resolves from store, not stale REST snapshot', async () => {
    const { wrapper } = await mountModal()

    const icon = wrapper.vm.executionModeIcon
    expect(icon.img).toBe(null)
    expect(icon.icon).toBe('mdi-connection')
  })

  it('folds a legacy per-CLI execution_mode token to "Subagent" when project is not tracked in the store', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)

    api.projects.review = vi.fn().mockResolvedValue(makeReviewResponse('codex_cli'))

    const wrapper = mount(ProjectReviewModal, {
      props: { show: false, projectId: PROJECT_ID },
      global: { plugins: [pinia, vuetify, hubRouter] },
    })

    await wrapper.setProps({ show: true })
    await flushPromises()

    expect(wrapper.vm.executionModeLabel).toBe('Subagent')
  })
})


describe('ProjectReviewModal.vue — Project Comms pane (Phase 5 / D1(a))', () => {
  const BOUND = {
    thread_id: 'thr-bound',
    project_id: PROJECT_ID,
    subject: '(project comms)',
    created_at: '2026-06-01T00:00:00Z',
  }

  beforeEach(() => {
    api.projects.review = vi.fn().mockResolvedValue(makeReviewResponse('multi_terminal'))
  })

  it('shows the empty state when the project has no bound thread', async () => {
    api.threads = {
      list: vi.fn().mockResolvedValue({ data: { threads: [] } }),
      history: vi.fn().mockResolvedValue({ data: { thread: null, messages: [] } }),
      create: vi.fn(),
    }
    const { wrapper } = await mountModal()
    await flushPromises()
    expect(wrapper.find('[data-testid="project-comms-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="project-comms-timeline"]').exists()).toBe(false)
  })

  it('renders the bound thread timeline + Open-in-Hub deep link when one exists', async () => {
    api.threads = {
      list: vi.fn().mockResolvedValue({ data: { threads: [BOUND] } }),
      history: vi.fn().mockResolvedValue({
        data: {
          thread: BOUND,
          messages: [
            { thread_id: 'thr-bound', message_id: 'm1', from_agent_id: 'implementer', content: 'hi', created_at: '2026-06-01T01:00:00Z' },
          ],
        },
      }),
      create: vi.fn(),
    }
    const { wrapper } = await mountModal()
    await flushPromises()
    expect(wrapper.find('[data-testid="project-comms-timeline"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="project-comms-open-hub"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="project-comms-empty"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="timeline-message-m1"]').exists()).toBe(true)
  })

  it('deep-links to the Hub on the bound thread when Open-in-Hub is clicked', async () => {
    api.threads = {
      list: vi.fn().mockResolvedValue({ data: { threads: [BOUND] } }),
      history: vi.fn().mockResolvedValue({
        data: { thread: BOUND, messages: [] },
      }),
      create: vi.fn(),
    }
    const { wrapper } = await mountModal()
    await flushPromises()

    await wrapper.find('[data-testid="project-comms-open-hub"]').trigger('click')
    await flushPromises()

    expect(hubRouter.currentRoute.value.name).toBe('Hub')
    expect(hubRouter.currentRoute.value.query).toEqual({
      thread: 'thr-bound',
      tab: 'project',
    })
    expect(wrapper.emitted('close')).toBeTruthy()
  })
})


describe('ProjectReviewModal.vue — superseded successor notice (FE-9591)', () => {
  const SUCCESSOR_ID = 'proj-successor-9591'

  function supersededResponse(successorId) {
    return {
      data: {
        project: {
          id: PROJECT_ID,
          project_id: PROJECT_ID,
          name: 'The old project',
          status: 'superseded',
          successor_project_id: successorId,
          agents: [],
        },
        agent_jobs: [],
        memory_entries: [],
      },
    }
  }

  function makeRouter() {
    return createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'Root', component: { template: '<div />' } },
        { path: '/hub', name: 'Hub', component: { template: '<div />' } },
        {
          path: '/projects/:projectId',
          name: 'ProjectLaunch',
          component: { template: '<div />' },
        },
      ],
    })
  }

  async function mountWith(reviewResponse, router) {
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(ProjectReviewModal, {
      props: { show: false, projectId: PROJECT_ID },
      global: { plugins: [pinia, vuetify, router] },
    })
    api.projects.review = vi.fn().mockResolvedValue(reviewResponse)
    await wrapper.setProps({ show: true })
    await flushPromises()
    return wrapper
  }

  beforeEach(() => {
    api.threads = {
      list: vi.fn().mockResolvedValue({ data: { threads: [] } }),
      history: vi.fn().mockResolvedValue({ data: { thread: null, messages: [] } }),
      create: vi.fn(),
    }
    api.projects.get = vi.fn().mockResolvedValue({
      data: { id: SUCCESSOR_ID, name: 'The replacement project', taxonomy_alias: 'FE-9999' },
    })
  })

  it('names the successor and links to it', async () => {
    const router = makeRouter()
    const wrapper = await mountWith(supersededResponse(SUCCESSOR_ID), router)

    expect(api.projects.get).toHaveBeenCalledWith(SUCCESSOR_ID)
    const link = wrapper.find('[data-testid="superseded-successor-link"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toContain('The replacement project')
    expect(link.text()).toContain('FE-9999')

    await link.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('ProjectLaunch')
    expect(router.currentRoute.value.params.projectId).toBe(SUCCESSOR_ID)
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('falls back to the raw id when the successor row cannot be resolved', async () => {
    api.projects.get = vi.fn().mockRejectedValue(new Error('boom'))
    const wrapper = await mountWith(supersededResponse(SUCCESSOR_ID), makeRouter())

    const link = wrapper.find('[data-testid="superseded-successor-link"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toContain(SUCCESSOR_ID)
  })

  it('says the replacement was not recorded when the pointer is missing', async () => {
    const wrapper = await mountWith(supersededResponse(null), makeRouter())

    expect(wrapper.find('[data-testid="superseded-notice"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="superseded-successor-link"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="superseded-notice-unknown"]').text()).toContain(
      'not recorded',
    )
    expect(api.projects.get).not.toHaveBeenCalled()
  })

  it('renders no successor line for a project that is not superseded', async () => {
    const wrapper = await mountWith(makeReviewResponse('multi_terminal'), makeRouter())

    expect(wrapper.find('[data-testid="superseded-notice"]').exists()).toBe(false)
    expect(api.projects.get).not.toHaveBeenCalled()
  })
})
