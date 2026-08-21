/**
 * HubView.threadHeader.spec.js — FE-9289c
 *
 * The thread header is the SHARING moment: it is where the operator hands a thread id
 * to an agent, so it carries the id with a `join_thread <id>` hint (DoD 5) and the
 * second rename affordance (DoD 3 — "from both the card AND the thread header").
 *
 * A project thread is named after its project and kept with its 360 memory, so the
 * pencil becomes a lock that SAYS WHY rather than a button that quietly vanishes.
 * That is the same rule BE-9289b enforces server-side; here it must be legible.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createVuetify } from 'vuetify'

vi.mock('@/services/api', () => ({
  default: { threads: { list: vi.fn().mockResolvedValue({ data: { threads: [] } }) } },
}))
vi.mock('@/stores/websocketEventRouter', () => ({ registerReconnectResync: () => () => {} }))
// FE-9410: HubView now pushes routes as well as reading them (the attention strip
// navigates instead of selecting in place), so the mock has to answer useRouter too.
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ push: vi.fn() }) }))

const toasts = []
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: (t) => toasts.push(t) }),
}))
const copySpy = vi.fn().mockResolvedValue(true)
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: copySpy }) }))

import HubView from '@/views/HubView.vue'
import { useCommHubStore } from '@/stores/commHubStore'

const vuetify = createVuetify()
const GENERAL_ID = '11111111-1111-4111-8111-111111111111'
const PROJECT_ID = '22222222-2222-4222-8222-222222222222'

const STUBS = {
  ThreadList: true,
  ThreadTimeline: true,
  HubComposer: true,
  NewThreadDialog: true,
  ThreadCreatedDialog: true,
  ThreadDeletedDialog: true,
}

function mountHub(pinia) {
  return mount(HubView, { global: { plugins: [pinia, vuetify], stubs: STUBS } })
}

function seed(store, thread) {
  store.threadsById = new Map([[thread.thread_id, thread]])
  store.selectedThreadId = thread.thread_id
}

describe('HubView thread header (FE-9289c)', () => {
  let pinia
  let store

  beforeEach(() => {
    toasts.length = 0
    copySpy.mockClear()
    pinia = createPinia()
    setActivePinia(pinia)
    store = useCommHubStore()
  })

  it('shows nothing until a thread is selected', () => {
    const wrapper = mountHub(pinia)
    expect(wrapper.find('[data-testid="thread-header"]').exists()).toBe(false)
  })

  it('titles the thread and shows the id with the join_thread hint', () => {
    seed(store, { thread_id: GENERAL_ID, subject: 'Laptop interop', title: 'Laptop interop', project_id: null })
    const wrapper = mountHub(pinia)
    expect(wrapper.get('[data-testid="thread-header-title"]').text()).toBe('Laptop interop')
    const id = wrapper.get('[data-testid="thread-header-id"]').text()
    expect(id).toContain('join_thread')
    // the UUID, not the CHT alias — the UUID is what an agent needs
    expect(id).toContain(GENERAL_ID)
  })

  it('renames from the header through the store action', async () => {
    seed(store, { thread_id: GENERAL_ID, subject: 'old name', project_id: null })
    const rename = vi.spyOn(store, 'renameThread').mockResolvedValue({})
    const wrapper = mountHub(pinia)
    await wrapper.get('[data-testid="thread-header-rename"]').trigger('click')
    const input = wrapper.get('[data-testid="thread-header-rename-input"]')
    await input.setValue('new name')
    await input.trigger('keydown.enter')
    expect(rename).toHaveBeenCalledWith(GENERAL_ID, 'new name')
    expect(toasts.at(-1)).toMatchObject({ type: 'success' })
  })

  it('surfaces the server refusal instead of pretending the rename worked', async () => {
    seed(store, { thread_id: GENERAL_ID, subject: 'old name', project_id: null })
    vi.spyOn(store, 'renameThread').mockRejectedValue({
      response: { data: { detail: 'kept with the project 360 memory' } },
    })
    const wrapper = mountHub(pinia)
    await wrapper.get('[data-testid="thread-header-rename"]').trigger('click')
    const input = wrapper.get('[data-testid="thread-header-rename-input"]')
    await input.setValue('new name')
    await input.trigger('keydown.enter')
    await Promise.resolve()
    expect(toasts.at(-1)).toMatchObject({ type: 'error', message: 'kept with the project 360 memory' })
  })

  it('a project thread shows a LOCK that explains itself — never a missing button', async () => {
    seed(store, { thread_id: PROJECT_ID, subject: '(project comms)', title: 'Sprint ledger', project_id: 'p-1' })
    const rename = vi.spyOn(store, 'renameThread')
    const wrapper = mountHub(pinia)
    const btn = wrapper.get('[data-testid="thread-header-rename"]')
    expect(btn.exists()).toBe(true)
    expect(btn.html()).toContain('mdi-lock-outline')
    await btn.trigger('click')
    // it explains, it does not open an editor and it does not call the API
    expect(wrapper.find('[data-testid="thread-header-rename-input"]').exists()).toBe(false)
    expect(rename).not.toHaveBeenCalled()
    expect(toasts.at(-1).message).toContain('named after their project')
  })

  it('states the right scope note per thread kind', () => {
    seed(store, { thread_id: GENERAL_ID, subject: 'General', project_id: null })
    expect(mountHub(pinia).get('[data-testid="thread-header-scope"]').text()).toContain('next poll')

    seed(store, { thread_id: PROJECT_ID, subject: 'Bound', project_id: 'p-1' })
    expect(mountHub(pinia).get('[data-testid="thread-header-scope"]').text()).toContain('Audit record')
  })

  it('copies the thread UUID', async () => {
    seed(store, { thread_id: GENERAL_ID, subject: 'General', chat_id: 'CHT-0461', project_id: null })
    const wrapper = mountHub(pinia)
    await wrapper.get('[data-testid="thread-header-copy"]').trigger('click')
    expect(copySpy).toHaveBeenCalledWith(GENERAL_ID)
  })
})
