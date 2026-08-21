/**
 * HubView.markHandled.fe9439.spec.js — FE-9439 item 3
 *
 * THE BUG THIS PINS
 *
 * The operator follows a "waiting on you" notification into a thread, reads the post,
 * and clicks mark-handled. The baton clears server-side and the gold `Waiting on you`
 * flag stays on screen anyway.
 *
 * It is a STALE DEEP LINK, not a stale computed. The pin is rendered from the route:
 *
 *     /hub?thread=<id>&focus=baton&message=<id>
 *
 * `focus=baton` + `message=<id>` is the whole authority for the flag (FE-9418's exact
 * pinning, unified through `hubThreadRoute.js` by FE-9436). `onMarkHandled` cleared the
 * baton on the SERVER and nothing ever rewrote the URL — so the view was still being
 * told, by its own route, to pin a focus that no longer existed. The server call
 * succeeded and the flag survived, which is exactly what the operator reported.
 *
 * WHY THIS SPEC IS SHAPED THE WAY IT IS
 *
 * It drives `[data-testid="composer-mark-handled"]` — the control that ALREADY EXISTS on
 * master. That is deliberate and it is the difference between a reproduction and a
 * broken instrument: a spec that clicked a control this project has not built yet would
 * go red with "element not found", which proves nothing about the defect. Every
 * assertion below fails on unmodified master for the REASON the operator saw, and the
 * testid is carried onto the new toggle so this file is continuous across the change.
 *
 * `ThreadTimeline` and `HubComposer` are mounted FOR REAL rather than stubbed. The flag
 * is the thing under test; asserting on a stub's `data-focus` attribute would pin the
 * prop that feeds it, not the pixel the operator is complaining about.
 *
 * The router mock's `replace` applies the new query to the same reactive route object,
 * which is what a real router does to `useRoute()`. That is a faithful stand-in, not a
 * shortcut: on master nothing calls `replace` at all, so the route keeps `focus`, the
 * computed keeps resolving an id, and the flag keeps rendering. The red comes from the
 * product, never from the mock.
 *
 * Edition scope: Both
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { reactive, nextTick } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), route: null }))

// The vue-router MODULE mock — the second answer routerInjectionGuard.js (FE-9427)
// names as legitimate, and the one the sibling HubView specs already use.
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: h.push, replace: h.replace }),
  useRoute: () => h.route,
}))
vi.mock('@/stores/websocketEventRouter', () => ({ registerReconnectResync: () => () => {} }))

const showToastMock = vi.fn()
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

import HubView from '@/views/HubView.vue'
import api from '@/services/api'
import { useCommHubStore } from '@/stores/commHubStore'
import { useUserStore } from '@/stores/user'

const ME = 'user-op-1'
const THREAD_ID = 'thr-9439'
const BATON_MESSAGE = 'msg-baton-9439'
const OTHER_MESSAGE = 'msg-other-9439'

// Only the children that are NOT under test. ThreadTimeline and HubComposer are real:
// one renders the flag, the other carries the control that clears it.
const childStubs = {
  ThreadList: { template: '<div class="stub-thread-list" />' },
  AgentPill: { template: '<span class="stub-pill" />' },
  NewThreadDialog: { template: '<div />' },
  ThreadCreatedDialog: { template: '<div />' },
  ThreadDeletedDialog: { template: '<div />' },
  DeletedCountButton: { props: ['count', 'entity'], template: '<button class="stub-deleted" />' },
}

function batonThread() {
  return {
    thread_id: THREAD_ID,
    chat_id: 'CHT-9439',
    subject: 'Baton thread',
    status: 'open',
    project_id: null,
    next_action_owner: ME,
    last_message: {
      id: BATON_MESSAGE,
      author: 'L25',
      excerpt: 'over to you',
      created_at: '2026-08-15T05:00:00Z',
    },
  }
}

async function mountHub() {
  h.push.mockClear()
  h.replace.mockClear()
  showToastMock.mockClear()

  // ONE reactive route object for the life of the mount, so a `replace` is observable
  // by the same computed the product reads — as it is in a real app.
  h.route = reactive({
    path: '/hub',
    query: { thread: THREAD_ID, focus: 'baton', message: BATON_MESSAGE },
  })
  h.replace.mockImplementation((to) => {
    h.route.query = { ...(to?.query || {}) }
    return Promise.resolve()
  })

  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useCommHubStore()
  const thread = batonThread()
  store._testSeedThread(thread)
  api.threads.history.mockResolvedValue({
    data: {
      thread,
      messages: [
        { message_id: BATON_MESSAGE, thread_id: THREAD_ID, content: 'over to you' },
        { message_id: OTHER_MESSAGE, thread_id: THREAD_ID, content: 'and one more thing' },
      ],
    },
  })
  useUserStore().currentUser = { id: ME, role: 'admin' }

  const wrapper = mount(HubView, { global: { plugins: [pinia], stubs: childStubs } })
  await flushPromises()
  await nextTick()
  return { wrapper, store }
}

const batonFlag = (wrapper) => wrapper.find('[data-testid="hub-focus-baton"]')

describe('FE-9439 — mark handled clears the "Waiting on you" pin', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  /**
   * MUST PASS ON BOTH SIDES OF THIS CHANGE.
   *
   * If this one goes red, the instrument is broken and every verdict in this file is
   * void — the arrival state itself failed to render, so a "flag is gone" assertion
   * downstream would be passing for the wrong reason. Checked first, deliberately.
   */
  it('renders the pin on arrival from a baton notification (instrument check)', async () => {
    const { wrapper } = await mountHub()

    expect(batonFlag(wrapper).exists()).toBe(true)
    expect(batonFlag(wrapper).text()).toBe('Waiting on you')
    expect(wrapper.find('[data-testid="composer-mark-handled"]').exists()).toBe(true)
  })

  it('clears the baton server-side (the half that already worked)', async () => {
    const { wrapper, store } = await mountHub()
    const passBatonSpy = vi
      .spyOn(store, 'passBaton')
      .mockResolvedValue({ thread_id: THREAD_ID, next_action_owner: null })

    await wrapper.get('[data-testid="composer-mark-handled"]').trigger('click')
    await flushPromises()

    expect(passBatonSpy).toHaveBeenCalledTimes(1)
    expect(passBatonSpy).toHaveBeenCalledWith(THREAD_ID, 'none')
  })

  /**
   * DoD 2 — two places to reach the action, ONE implementation of it.
   *
   * Driven per instance in its own mount rather than clicking both in one, because the
   * first click clears the baton and the second toggle would correctly be inert by then.
   * Testing them separately is what lets each one be asserted while it is live.
   */
  describe('both instances are the same control', () => {
    it.each([
      ['search bar', 'search-mark-handled'],
      ['composer', 'composer-mark-handled'],
    ])('the %s toggle issues exactly one passBaton(threadId, none)', async (_label, testid) => {
      const { wrapper, store } = await mountHub()
      const passBatonSpy = vi
        .spyOn(store, 'passBaton')
        .mockResolvedValue({ thread_id: THREAD_ID, next_action_owner: null })

      const instance = wrapper.get(`[data-testid="${testid}"]`)
      // Same shared component in both places — not two buttons that merely look alike.
      expect(instance.classes()).toContain('mark-handled-toggle')

      await instance.trigger('click')
      await flushPromises()

      expect(passBatonSpy).toHaveBeenCalledTimes(1)
      expect(passBatonSpy).toHaveBeenCalledWith(THREAD_ID, 'none')
      // And the route fix travels with whichever one was pressed.
      expect(h.route.query.focus).toBeUndefined()
    })

    it('renders both instances while the turn is the operator, ON', async () => {
      const { wrapper } = await mountHub()

      for (const testid of ['search-mark-handled', 'composer-mark-handled']) {
        const instance = wrapper.get(`[data-testid="${testid}"]`)
        expect(instance.attributes('aria-pressed')).toBe('true')
        expect(instance.attributes('color')).toBe('warning')
      }
    })
  })

  /**
   * THE REGRESSION. Red on master, at the assertion, for the operator's reason.
   */
  it('drops focus/message from the route so the pin cannot survive', async () => {
    const { wrapper, store } = await mountHub()
    vi.spyOn(store, 'passBaton').mockResolvedValue({ thread_id: THREAD_ID, next_action_owner: null })

    await wrapper.get('[data-testid="composer-mark-handled"]').trigger('click')
    await flushPromises()
    await nextTick()

    // The route no longer claims a focus...
    expect(h.route.query.focus).toBeUndefined()
    expect(h.route.query.message).toBeUndefined()
    // ...and the thread the operator is reading is NOT thrown away with it.
    expect(h.route.query.thread).toBe(THREAD_ID)
    // `replace`, never `push` — clearing a stale flag is not a place in history the
    // operator can meaningfully go Back to.
    expect(h.replace).toHaveBeenCalledTimes(1)
    expect(h.push).not.toHaveBeenCalled()

    // And the pixel the operator complained about is gone.
    expect(batonFlag(wrapper).exists()).toBe(false)
  })

  /**
   * A failed clear must not lie. If the server refused, the baton is still pointed at
   * the operator, so removing the flag would hide live state behind a successful-looking
   * click. The route is only rewritten on success.
   */
  it('leaves the pin alone when the server refuses', async () => {
    const { wrapper, store } = await mountHub()
    vi.spyOn(store, 'passBaton').mockRejectedValue(new Error('nope'))

    await wrapper.get('[data-testid="composer-mark-handled"]').trigger('click')
    await flushPromises()
    await nextTick()

    expect(h.replace).not.toHaveBeenCalled()
    expect(h.route.query.focus).toBe('baton')
    expect(batonFlag(wrapper).exists()).toBe(true)
  })
})
