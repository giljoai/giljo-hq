/**
 * SystemStatusBanner.threadpost.fe9589.spec.js — FE-9589
 *
 * The thread-post row, wired to its parent. Two defects meet here and both are
 * pinned below.
 *
 * THE PERMANENT BANNER. A mention stops being reported only once the viewer's
 * read watermark passes the naming post, and the only client-side writer was
 * commHubStore.selectThread() -- which needs a thread to select. With two or
 * more entries live the row emits a null thread id, so the parent landed on the
 * Hub LIST, which selects nothing and writes no watermark. Agents keep posting,
 * so the row could never empty. The multi-entry CTA now advances the watermark
 * across EVERY thread the row names.
 *
 * THE MISSING DISMISS. The row had no close control on the reasoning that
 * reading the thread cleared it -- true in principle, and impossible via the
 * only action it offered. The operator ruled every banner closeable where it
 * stands. Dismissal is per-user, survives a reload, and writes no server state.
 *
 * Edition Scope: Both
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  // Resolves, like the real router: openThreadPost chains .catch() on the push.
  push: vi.fn(() => Promise.resolve()),
  markRead: vi.fn(),
  attention: { value: { mentions: [], directed_action: [] } },
}))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))

vi.mock('@/services/configService', () => ({
  default: {
    fetchConfig: vi.fn().mockResolvedValue({}),
    getGiljoMode: vi.fn(() => 'ce'),
  },
}))

vi.mock('@/composables/useTutorialState', async (importOriginal) => ({
  ...(await importOriginal()),
  isActivateBreadcrumbArmed: () => false,
  clearActivateBreadcrumb: vi.fn(),
}))

vi.mock('@/composables/useOnboardingReminders', () => ({
  useOnboardingReminders: () => ({
    showIntegrationReminder: { value: () => false },
    showAgentReminder: { value: () => false },
    dismissIntegrationReminder: vi.fn(),
    dismissAgentReminder: vi.fn(),
  }),
}))

vi.mock('@/composables/useIntegrationStatus', async () => {
  const { ref } = await import('vue')
  return {
    useIntegrationStatus: () => ({
      gitEnabled: ref(true),
      serenaEnabled: ref(true),
      resolved: ref(true),
      loading: ref(false),
      refresh: vi.fn().mockResolvedValue(),
    }),
  }
})

vi.mock('@/services/api', () => {
  const apiObj = {
    stats: { getDashboard: vi.fn(() => Promise.resolve({ data: { project_status_dist: {} } })) },
    notifications: { list: vi.fn(), markRead: vi.fn(), markDismissed: vi.fn() },
    threads: {
      list: vi.fn(() => Promise.resolve({ data: { threads: [] } })),
      attention: vi.fn(() => Promise.resolve({ data: h.attention.value })),
      markRead: h.markRead,
    },
    approvals: { listPending: vi.fn(() => Promise.resolve({ data: { items: [] } })) },
  }
  return { default: apiObj, api: apiObj }
})

import SystemStatusBanner from './SystemStatusBanner.vue'
import { useUserStore } from '@/stores/user'
import { __resetThreadPostAttention } from '@/composables/useThreadPostAttention'

const ROW = '[data-testid="thread-post-banner"]'
const CTA = '[data-testid="thread-post-cta"]'
const DISMISS = '[data-testid="thread-post-banner-dismiss"]'

const globalStubs = { 'v-icon': { template: '<i class="v-icon"><slot /></i>' } }

function mention(n, messageId = `m-${n}`) {
  return { thread_id: `t-${n}`, chat_id: `CHT-000${n}`, message_ids: [messageId] }
}

// tests/setup.js replaces window.localStorage with no-op vi.fn()s; the dismissal
// state under test IS localStorage, so install a working in-memory one per case.
function installFunctionalLocalStorage() {
  const store = new Map()
  Object.defineProperty(window, 'localStorage', {
    value: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
      clear: () => store.clear(),
    },
    writable: true,
  })
}

async function mountBanner({ mentions = [], directedAsks = [] } = {}) {
  h.attention.value = { mentions, directed_action: directedAsks }
  // The attention projection is MODULE-scoped on purpose (one answer for banner,
  // popout and notification path), so it has to be reset between cases.
  __resetThreadPostAttention()
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(SystemStatusBanner, { global: { plugins: [pinia], stubs: globalStubs } })
  useUserStore().currentUser = { id: 'user-op-1', role: 'admin' }
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('SystemStatusBanner thread-post row (FE-9589)', () => {
  beforeEach(() => {
    h.push.mockClear()
    h.markRead.mockClear()
    h.markRead.mockResolvedValue({})
    installFunctionalLocalStorage()
  })

  it('advances the read watermark across EVERY named thread when several are live', async () => {
    const wrapper = await mountBanner({ mentions: [mention(1), mention(2), mention(3)] })
    expect(wrapper.find(ROW).exists()).toBe(true)

    await wrapper.find(CTA).trigger('click')
    await flushPromises()

    // This is the whole defect: before FE-9589 the CTA wrote no watermark at all,
    // so the row it was supposed to clear stayed up forever.
    expect(h.markRead.mock.calls.map((c) => c[0]).sort()).toEqual(['t-1', 't-2', 't-3'])
    expect(h.push).toHaveBeenCalledWith({ path: '/hub' })
  })

  it('leaves the ONE-mention path exactly as it was: deep-link, no batch write', async () => {
    const wrapper = await mountBanner({ mentions: [mention(9)] })

    await wrapper.find(CTA).trigger('click')
    await flushPromises()

    // selectThread does the watermark write on arrival; the banner must not
    // pre-empt it, or the single-mention path acquires a second writer.
    expect(h.markRead).not.toHaveBeenCalled()
    expect(h.push).toHaveBeenCalledWith({
      path: '/hub',
      query: { thread: 't-9', focus: 'baton' },
    })
  })

  it('the dismiss X closes the row and writes no server state', async () => {
    const wrapper = await mountBanner({ mentions: [mention(1), mention(2)] })

    await wrapper.find(DISMISS).trigger('click')
    await flushPromises()

    expect(wrapper.find(ROW).exists()).toBe(false)
    // The obligation is NOT lost: no watermark moved, so the posts are still
    // unread and still reachable from the Hub and the bell.
    expect(h.markRead).not.toHaveBeenCalled()
    expect(h.push).not.toHaveBeenCalled()
  })

  it('keeps the dismissal across a remount -- hidden is not dismissed', async () => {
    const first = await mountBanner({ mentions: [mention(1)] })
    await first.find(DISMISS).trigger('click')
    await flushPromises()
    first.unmount()

    const second = await mountBanner({ mentions: [mention(1)] })
    expect(second.find(ROW).exists()).toBe(false)
  })

  it('announces again when a NEW post names the operator in the same thread', async () => {
    const first = await mountBanner({ mentions: [mention(1, 'm-old')] })
    await first.find(DISMISS).trigger('click')
    await flushPromises()
    first.unmount()

    // The mention key names the newest naming post, so a further one is a new
    // obligation rather than the one that was waved away.
    const second = await mountBanner({ mentions: [mention(1, 'm-new')] })
    expect(second.find(ROW).exists()).toBe(true)
  })

  it('re-announces a directed ask that recurs on a thread whose ask was dismissed', async () => {
    // The projection reports a directed ask per THREAD with no post id, so its
    // dismissal key cannot change on its own. Reconciliation is what stops the
    // dismissal outliving the ask: once the projection (hydrated) no longer
    // reports it, the stored key is dropped.
    const ask = { thread_id: 'a-1', chat_id: 'CHT-1001' }
    const first = await mountBanner({ directedAsks: [ask] })
    await first.find(DISMISS).trigger('click')
    await flushPromises()
    first.unmount()

    // The ask is acknowledged: nothing is waiting.
    const quiet = await mountBanner({})
    expect(quiet.find(ROW).exists()).toBe(false)
    quiet.unmount()

    // A NEW ask on that same thread must announce itself.
    const third = await mountBanner({ directedAsks: [ask] })
    expect(third.find(ROW).exists()).toBe(true)
  })
})
