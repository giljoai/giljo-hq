import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ list: null, push: vi.fn(), patch: vi.fn(), routeName: undefined, routeQuery: {} }))

vi.mock('vue-router', () => ({
  useRoute: () => ({ meta: {}, query: h.routeQuery, name: h.routeName }),
  useRouter: () => ({ push: h.push }),
}))
vi.mock('@/services/api', () => {
  const apiObj = {
    auth: { updateSetupState: (...a) => h.patch(...a), me: vi.fn() },
    onboarding: { startList: vi.fn(async () => ({ data: JSON.parse(JSON.stringify(h.list)) })) },
  }
  return { default: apiObj, api: apiObj }
})
vi.mock('@/composables/useClipboard', () => ({ useClipboard: () => ({ copy: vi.fn() }) }))
vi.mock('@/composables/useStarterProject', () => ({
  useStarterProject: () => ({ createFromTemplate: vi.fn(), busyTemplateId: { value: null } }),
}))
vi.mock('@/stores/products', () => ({ useProductStore: () => ({ effectiveProductId: 'prod-1' }) }))

import GuidePane from '@/components/onboarding/GuidePane.vue'
import { useGuideStore } from '@/stores/guide'
import { useStartListStore } from '@/stores/startList'
import { useUserStore } from '@/stores/user'
import { NUDGE_AFTER_MS } from '@/content/onboarding/guide'
import { startListPayload, ALL_DONE } from '../../../tests/helpers/startListRows'

const mem = new Map()
window.localStorage = {
  getItem: (k) => (mem.has(k) ? mem.get(k) : null),
  setItem: (k, v) => mem.set(k, String(v)),
  removeItem: (k) => mem.delete(k),
  clear: () => mem.clear(),
}

const CONNECTED = { tool_connected: { done: true, live: true, tool_name: 'Claude Code' } }
const SETUP = { ...CONNECTED, skills_installed: { done: true } }
const PROJECT = {
  ...SETUP,
  product_exists: { done: true, product_name: 'Recipe Box' },
  project_created: { done: true, project_id: 'p-9', project_name: 'Add a search box' },
}
const NUDGE_LINE = 'Stuck? The video shows each press.'

async function mountPane(over = {}, { user = {} } = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  h.list = startListPayload(over)
  useUserStore().currentUser = {
    id: 'u-1', created_at: '2026-11-16T10:00:00Z', guide_closed: false, intro_video_seen: true, ...user,
  }
  await useStartListStore().refresh()
  const guide = useGuideStore()
  const w = mount(GuidePane, {
    global: { plugins: [pinia], stubs: { StartProductDialog: true, IntroVideoDialog: true } },
  })
  await flushPromises()
  return { w, guide, pinia }
}
const id = (w, t) => w.find(`[data-testid="${t}"]`)
const nudgedRows = (w) => [1, 2, 3, 4, 5, 6].filter((n) => id(w, `guide-row-${n}`).attributes('data-nudged') === 'true')
const tick = async (ms) => {
  await vi.advanceTimersByTimeAsync(ms)
  await flushPromises()
}
async function moveTo(over) {
  h.list = startListPayload(over)
  await useStartListStore().refresh({ force: true })
  await flushPromises()
}

describe('GuidePane nudge: when it fires', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mem.clear()
    window.innerWidth = 1280
    h.patch.mockReset()
    h.patch.mockImplementation(async (p) => ({ data: p }))
    h.push.mockClear()
    h.routeName = undefined
    h.routeQuery = {}
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('the constant is five minutes', () => {
    expect(NUDGE_AFTER_MS).toBe(5 * 60 * 1000)
  })

  it('not at 4:59, at 5:00: the current row, its button pulses (the one existing class) and the help line changes', async () => {
    const { w } = await mountPane(CONNECTED)
    expect(nudgedRows(w)).toEqual([])
    await tick(NUDGE_AFTER_MS - 1000)
    expect(nudgedRows(w)).toEqual([])
    expect(id(w, 'guide-row-2-play').classes()).not.toContain('next-press-pulse')
    await tick(1000)
    expect(nudgedRows(w)).toEqual([2])
    expect(id(w, 'guide-row-2-play').classes()).toContain('next-press-pulse')
    expect(id(w, 'guide-row-2-line').text()).toBe(NUDGE_LINE)
  })

  it('only one row pulses, and a done or not-current row never does', async () => {
    const { w } = await mountPane(CONNECTED)
    await tick(NUDGE_AFTER_MS)
    expect(w.findAll('.next-press-pulse')).toHaveLength(1)
    for (const n of [1, 3, 4, 5, 6]) expect(id(w, `guide-row-${n}-play`).classes()).not.toContain('next-press-pulse')
  })

  it('playing the row\'s video stops the nudge for good, also after a reload and another 10 minutes', async () => {
    const { w } = await mountPane(CONNECTED)
    await tick(NUDGE_AFTER_MS)
    await id(w, 'guide-row-2-play').trigger('click')
    await flushPromises()
    expect(nudgedRows(w)).toEqual([])
    expect(id(w, 'guide-row-2-line').text()).toBe('Ask your tool to run giljo_setup.')
    const again = await mountPane(CONNECTED)
    await tick(2 * NUDGE_AFTER_MS)
    expect(nudgedRows(again.w)).toEqual([])
  })

  it('a row that is done before the five minutes is never nudged, and the next row starts its own clock', async () => {
    const { w } = await mountPane(CONNECTED)
    await tick(NUDGE_AFTER_MS - 1000)
    await moveTo(SETUP)
    expect(id(w, 'guide-row-2').attributes('data-state')).toBe('done')
    await tick(2000)
    expect(nudgedRows(w)).toEqual([])
    await tick(NUDGE_AFTER_MS - 3000)
    expect(nudgedRows(w)).toEqual([])
    await tick(2000)
    expect(nudgedRows(w)).toEqual([3])
  })

  it('closing the guide before the five minutes cancels the clock: nothing is remembered as nudged', async () => {
    const { w } = await mountPane(CONNECTED)
    await tick(NUDGE_AFTER_MS - 1000)
    await id(w, 'guide-pane-close').trigger('click')
    await flushPromises()
    await tick(5000)
    expect([...mem.values()].join('')).not.toContain('guide:nudge-fired')
  })

  it('a row that is done after it was nudged stops, and stays stopped if the fact flips back', async () => {
    const { w } = await mountPane(CONNECTED)
    await tick(NUDGE_AFTER_MS)
    expect(nudgedRows(w)).toEqual([2])
    await moveTo(SETUP)
    expect(nudgedRows(w)).toEqual([])
    expect(id(w, 'guide-row-2-play').classes()).not.toContain('next-press-pulse')
    await moveTo(CONNECTED)
    await tick(2 * NUDGE_AFTER_MS)
    expect(nudgedRows(w)).toEqual([])
  })

  it('once nudged it stays nudged after a reload (remembered per account and browser), without a new clock', async () => {
    await mountPane(CONNECTED)
    await tick(NUDGE_AFTER_MS)
    const again = await mountPane(CONNECTED)
    expect(nudgedRows(again.w)).toEqual([2])
    expect([...mem.keys()].some((k) => k.startsWith('giljo_banner_dismissals_u-1'))).toBe(true)
  })

  it('another account in the same browser is not nudged by it', async () => {
    await mountPane(CONNECTED)
    await tick(NUDGE_AFTER_MS)
    const other = await mountPane(CONNECTED, { user: { id: 'u-2' } })
    expect(nudgedRows(other.w)).toEqual([])
  })

  it('a reload restarts the clock', async () => {
    await mountPane(CONNECTED)
    await tick(NUDGE_AFTER_MS - 60000)
    const again = await mountPane(CONNECTED)
    await tick(NUDGE_AFTER_MS - 60000)
    expect(nudgedRows(again.w)).toEqual([])
    await tick(60000)
    expect(nudgedRows(again.w)).toEqual([2])
  })

  it('time with the tab hidden does not count', async () => {
    const hidden = vi.spyOn(document, 'hidden', 'get')
    hidden.mockReturnValue(false)
    const { w } = await mountPane(CONNECTED)
    await tick(3 * 60000)
    hidden.mockReturnValue(true)
    document.dispatchEvent(new Event('visibilitychange'))
    await tick(30 * 60000)
    expect(nudgedRows(w)).toEqual([])
    hidden.mockReturnValue(false)
    document.dispatchEvent(new Event('visibilitychange'))
    await tick(2 * 60000 - 1000)
    expect(nudgedRows(w)).toEqual([])
    await tick(1000)
    expect(nudgedRows(w)).toEqual([2])
    hidden.mockRestore()
  })

  it('never while the intro video is pending', async () => {
    const { w } = await mountPane(CONNECTED, { user: { intro_video_seen: false } })
    await tick(2 * NUDGE_AFTER_MS)
    expect(w.find('[data-testid="guide-pane"]').exists()).toBe(false)
    expect(useGuideStore().nudgedRow).toBe(null)
  })

  it('never on a closed guide, and never on a finished one', async () => {
    const closed = await mountPane(CONNECTED, { user: { guide_closed: true } })
    await tick(2 * NUDGE_AFTER_MS)
    expect(closed.guide.nudgedRow).toBe(null)
    const done = await mountPane(ALL_DONE.rows)
    await done.guide.turnOn()
    await flushPromises()
    await tick(2 * NUDGE_AFTER_MS)
    expect(done.guide.nudgedRow).toBe(null)
    expect(nudgedRows(done.w)).toEqual([])
  })

  it('a status row (requested) keeps its status line and gets the nudge line beside it', async () => {
    const { w } = await mountPane({ ...PROJECT, project_staged: { requested: true } })
    await tick(NUDGE_AFTER_MS)
    expect(nudgedRows(w)).toEqual([5])
    expect(id(w, 'guide-row-5-line').text()).toBe('Prompt copied. Paste it in your AI tool. Your tool writes the plan.')
    expect(id(w, 'guide-row-5-nudge').text()).toBe(NUDGE_LINE)
  })

  it('rows are centred groups: the buttons sit in the wrapping, centred group', async () => {
    const { w } = await mountPane(PROJECT)
    for (const n of [4, 5]) expect(id(w, `guide-row-${n}-buttons`).classes()).toContain('gp-actions')
  })
})

describe('GuidePane: Show me the card', () => {
  const staged = { ...PROJECT, project_staged: { done: true, mode: 'subagent' } }
  const review = { ...staged, project_built: { awaiting_review: true } }
  beforeEach(() => {
    mem.clear()
    window.innerWidth = 1280
    h.patch.mockReset()
    h.patch.mockImplementation(async (p) => ({ data: p }))
    h.push.mockClear()
    h.routeName = undefined
    h.routeQuery = {}
  })

  it('awaiting review: a text link opens the Implementation side of the board; Go to Projects is not there', async () => {
    const { w } = await mountPane(review)
    const link = id(w, 'guide-row-6-card')
    expect(link.text()).toBe('Show me the card')
    expect(link.classes()).not.toContain('gp-btn')
    expect(id(w, 'guide-row-6-goto').exists()).toBe(false)
    await link.trigger('click')
    expect(h.push).toHaveBeenCalledWith({ name: 'JobsViewport', query: { side: 'implementation' } })
  })

  it('shown on the Projects page and on the Staging side, not on the Implementation side', async () => {
    h.routeName = 'Projects'
    expect(id((await mountPane(review)).w, 'guide-row-6-card').exists()).toBe(true)
    h.routeName = 'JobsViewport'
    h.routeQuery = { side: 'staging' }
    expect(id((await mountPane(review)).w, 'guide-row-6-card').exists()).toBe(true)
    h.routeQuery = { side: 'implementation' }
    expect(id((await mountPane(review)).w, 'guide-row-6-card').exists()).toBe(false)
  })

  it('not in the other row 6 states; "Go to Projects" stays for todo', async () => {
    const todo = await mountPane(staged)
    expect(id(todo.w, 'guide-row-6-card').exists()).toBe(false)
    expect(id(todo.w, 'guide-row-6-goto').exists()).toBe(true)
    const running = await mountPane({ ...staged, project_built: { in_progress: true } })
    expect(id(running.w, 'guide-row-6-card').exists()).toBe(false)
  })
})
