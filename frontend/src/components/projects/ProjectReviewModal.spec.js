/**
 * ProjectReviewModal.spec.js — FE-6021
 *
 * Regression test: executionModeLabel and executionModeIcon resolve from the
 * projectStateStore (store-first) rather than from the stale REST snapshot.
 *
 * This guards the bug class introduced by FE-6019 parity work — the modal's
 * REST call fires once on open (never re-fetched), so if execution_mode mutates
 * while the modal is open the two computeds go stale unless they prefer the
 * live store value.
 *
 * Edition scope: CE
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createVuetify } from 'vuetify'
import { createRouter, createMemoryHistory } from 'vue-router'
import ProjectReviewModal from '@/components/projects/ProjectReviewModal.vue'
import { useProjectStateStore } from '@/stores/projectStateStore'
import api from '@/services/api'

const vuetify = createVuetify()

// FE-9427: ProjectReviewModal calls useRouter() -- openInHub() pushes the named
// 'Hub' route. Mounted without a router that returned `undefined`, so the
// deep-link path was inert.
const hubRouter = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Root', component: { template: '<div />' } },
    { path: '/hub', name: 'Hub', component: { template: '<div />' } },
  ],
})

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const PROJECT_ID = 'proj-fe6021'

/**
 * Stale snapshot returned by the one-shot REST call.
 * execution_mode is 'multi_terminal' — this is the STALE value.
 * The store will have 'subagent' — the LIVE value.
 */
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

// ---------------------------------------------------------------------------
// Mount helper
// ---------------------------------------------------------------------------

async function mountModal() {
  const pinia = createPinia()
  setActivePinia(pinia)

  // Mount with show=false so the watcher does NOT fire immediately
  const wrapper = mount(ProjectReviewModal, {
    props: {
      show: false,
      projectId: PROJECT_ID,
    },
    global: {
      plugins: [pinia, vuetify, hubRouter],
    },
  })

  // Seed the store with the LIVE execution_mode BEFORE opening the modal.
  // This mirrors the real scenario: a WS event updates the store while the
  // project list is displayed; the user then opens the review modal.
  const projectStateStore = useProjectStateStore()
  projectStateStore.setProject({
    id: PROJECT_ID,
    project_id: PROJECT_ID,
    execution_mode: 'subagent',
  })

  // Open the modal — triggers the watcher → loadReviewData() → populates the
  // stale snapshot from the mocked API (multi_terminal)
  await wrapper.setProps({ show: true })
  await flushPromises()

  return { wrapper, projectStateStore }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ProjectReviewModal.vue — execution_mode store-first (FE-6021)', () => {
  beforeEach(() => {
    // tests/setup.js calls vi.clearAllMocks() per-test, but we also mock here
    // to set the return value that populates the stale snapshot.
    api.projects.review = vi.fn().mockResolvedValue(makeReviewResponse('multi_terminal'))
    // Phase 5 / D1(a): the modal now resolves the project's bound Hub thread on
    // open. Default to "no bound thread" so these execution-mode tests are
    // unaffected (the Project Comms section just renders its empty state).
    api.threads = {
      list: vi.fn().mockResolvedValue({ data: { threads: [] } }),
      history: vi.fn().mockResolvedValue({ data: { thread: null, messages: [] } }),
      create: vi.fn(),
    }
  })

  it('executionModeLabel resolves from store, not stale REST snapshot', async () => {
    const { wrapper } = await mountModal()

    // The store has 'subagent' → label 'Subagent'
    // The REST snapshot has 'multi_terminal' → label 'Multi-Terminal'
    // Store-first means we must see 'Subagent'
    expect(wrapper.vm.executionModeLabel).toBe('Subagent')
  })

  it('executionModeIcon resolves from store, not stale REST snapshot', async () => {
    const { wrapper } = await mountModal()

    // The store has 'subagent' → icon 'mdi-connection', img null
    // The REST snapshot has 'multi_terminal' → icon 'mdi-monitor-multiple'
    const icon = wrapper.vm.executionModeIcon
    expect(icon.img).toBe(null)
    expect(icon.icon).toBe('mdi-connection')
  })

  // BE-9035c: a pre-collapse project may still carry a tolerated-on-read
  // legacy per-CLI token (here 'codex_cli') — it must still fold to the
  // generic "Subagent" label/icon, not error or show a per-vendor label.
  it('folds a legacy per-CLI execution_mode token to "Subagent" when project is not tracked in the store', async () => {
    // Do NOT seed the store — simulate a project not tracked by any WS event.
    const pinia = createPinia()
    setActivePinia(pinia)

    // For this test the snapshot has the legacy 'codex_cli' token and the store is empty
    api.projects.review = vi.fn().mockResolvedValue(makeReviewResponse('codex_cli'))

    const wrapper = mount(ProjectReviewModal, {
      props: { show: false, projectId: PROJECT_ID },
      global: { plugins: [pinia, vuetify, hubRouter] },
    })

    await wrapper.setProps({ show: true })
    await flushPromises()

    // Store is empty → getProjectState returns null → falls back to snapshot,
    // which folds the legacy token to the generic Subagent label.
    expect(wrapper.vm.executionModeLabel).toBe('Subagent')
  })
})

// ---------------------------------------------------------------------------
// Phase 5 / D1(a): the read-only "Project Comms" section surfaces the project's
// bound Hub thread as a timeline, with a deep-link into the Hub for interaction.
// ---------------------------------------------------------------------------

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
    // the embedded read-only timeline shows the bound thread's message
    expect(wrapper.find('[data-testid="timeline-message-m1"]').exists()).toBe(true)
  })

  // FE-9427: the test above proves the deep link is RENDERED. Nothing proved
  // where it goes -- this spec mounted the modal with no router at all, so
  // useRouter() returned `undefined` and openInHub()'s push was unreachable.
  // With a real router installed the destination is assertable, so assert it:
  // a button that exists and navigates nowhere is the failure this pane would
  // actually have.
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
    // The modal closes behind the navigation -- one without the other would
    // leave the operator on the Hub with a dialog still open over it.
    expect(wrapper.emitted('close')).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// FE-9591: a superseded project's card says what replaced it.
//
// successor_project_id has ridden the review payload since BE-9157 and was
// rendered nowhere -- the pointer was captured, transmitted, and thrown away.
// These tests pin the three cases that matter: named link, missing pointer,
// and the normal case staying untouched.
// ---------------------------------------------------------------------------

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
    // Navigating away behind a still-open dialog would trap the operator.
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
    // A missing pointer must not trigger a lookup for nothing.
    expect(api.projects.get).not.toHaveBeenCalled()
  })

  it('renders no successor line for a project that is not superseded', async () => {
    const wrapper = await mountWith(makeReviewResponse('multi_terminal'), makeRouter())

    expect(wrapper.find('[data-testid="superseded-notice"]').exists()).toBe(false)
    expect(api.projects.get).not.toHaveBeenCalled()
  })
})
