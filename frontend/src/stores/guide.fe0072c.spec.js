import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

const h = vi.hoisted(() => ({ list: null, patch: vi.fn(), listCalls: 0 }))
vi.mock('@/services/api', () => {
  const apiObj = {
    auth: { updateSetupState: (...a) => h.patch(...a), me: vi.fn() },
    onboarding: {
      startList: vi.fn(async () => {
        h.listCalls += 1
        return { data: JSON.parse(JSON.stringify(h.list)) }
      }),
    },
  }
  return { default: apiObj, api: apiObj }
})

import { useGuideStore } from '@/stores/guide'
import { useStartListStore } from '@/stores/startList'
import { useUserStore } from '@/stores/user'
import { startListPayload, ALL_DONE } from '../../tests/helpers/startListRows'

const mem = new Map()
function installMemoryStorage() {
  mem.clear()
  window.localStorage = {
    getItem: (k) => (mem.has(k) ? mem.get(k) : null),
    setItem: (k, v) => mem.set(k, String(v)),
    removeItem: (k) => mem.delete(k),
    clear: () => mem.clear(),
  }
}

const AFTER = '2026-11-16T10:00:00Z'
const BEFORE = '2026-11-01T10:00:00Z'

async function setup({ user = {}, list = startListPayload() } = {}) {
  setActivePinia(createPinia())
  h.list = list
  const users = useUserStore()
  users.currentUser = {
    id: 'u-1', created_at: AFTER, guide_closed: false, intro_video_seen: true, ...user,
  }
  const guide = useGuideStore()
  await useStartListStore().refresh()
  await nextTick()
  return { guide, users }
}

describe('guide pane: when it shows by itself', () => {
  beforeEach(() => {
    installMemoryStorage()
    h.patch.mockReset()
    h.patch.mockImplementation(async (p) => ({ data: p }))
    h.listCalls = 0
  })

  it('an account created after the release, not closed, not finished: shows', async () => {
    const { guide } = await setup()
    expect(guide.visible).toBe(true)
  })

  it('an account created before the release: absent', async () => {
    const { guide } = await setup({ user: { created_at: BEFORE } })
    expect(guide.visible).toBe(false)
  })

  it('closed: absent', async () => {
    const { guide } = await setup({ user: { guide_closed: true } })
    expect(guide.visible).toBe(false)
  })

  it('finished when the page loads: stays out', async () => {
    const { guide } = await setup({ list: ALL_DONE })
    expect(guide.visible).toBe(false)
  })

  it('intro video still pending: absent', async () => {
    const { guide } = await setup({ user: { intro_video_seen: false } })
    expect(guide.visible).toBe(false)
  })

  it('not shown before the first read lands (no flash)', async () => {
    setActivePinia(createPinia())
    h.list = startListPayload()
    const users = useUserStore()
    users.currentUser = { id: 'u-1', created_at: AFTER, guide_closed: false, intro_video_seen: true }
    const guide = useGuideStore()
    expect(guide.visible).toBe(false)
  })

  it('a missing created_at never counts as new', async () => {
    const { guide } = await setup({ user: { created_at: undefined } })
    expect(guide.visible).toBe(false)
  })

  it('finishing while it is on screen keeps it (the finished state), not removing it', async () => {
    const { guide } = await setup()
    expect(guide.visible).toBe(true)
    h.list = ALL_DONE
    await useStartListStore().refresh({ force: true })
    await nextTick()
    expect(guide.finished).toBe(true)
    expect(guide.visible).toBe(true)
  })
})

describe('guide pane: close and turn on again', () => {
  beforeEach(() => {
    installMemoryStorage()
    h.patch.mockReset()
    h.patch.mockImplementation(async (p) => ({ data: p }))
  })

  it('close saves guide_closed true through the setup-state writer and hides it', async () => {
    const { guide, users } = await setup()
    await guide.close()
    expect(h.patch).toHaveBeenCalledWith({ guide_closed: true })
    expect(users.currentUser.guide_closed).toBe(true)
    expect(guide.visible).toBe(false)
  })

  it('a failed save still hides it for this visit', async () => {
    h.patch.mockRejectedValueOnce(new Error('offline'))
    const { guide } = await setup()
    await guide.close()
    expect(guide.visible).toBe(false)
  })

  it('turn on: saves guide_closed false, opens it, for any account', async () => {
    const { guide, users } = await setup({ user: { created_at: BEFORE, guide_closed: false } })
    expect(guide.visible).toBe(false)
    await guide.turnOn()
    expect(h.patch).toHaveBeenCalledWith({ guide_closed: false })
    expect(users.currentUser.guide_closed).toBe(false)
    expect(guide.visible).toBe(true)
    expect(guide.folded).toBe(false)
  })

  it('turn on after a close brings it back, even finished', async () => {
    const { guide } = await setup({ list: ALL_DONE, user: { guide_closed: true } })
    await guide.turnOn()
    expect(guide.visible).toBe(true)
    expect(guide.finished).toBe(true)
  })

  it('close, then turn on, then close again', async () => {
    const { guide } = await setup()
    await guide.close()
    await guide.turnOn()
    expect(guide.visible).toBe(true)
    await guide.close()
    expect(guide.visible).toBe(false)
  })
})

describe('guide pane: folded is remembered per browser', () => {
  beforeEach(() => {
    installMemoryStorage()
    h.patch.mockReset()
    h.patch.mockImplementation(async (p) => ({ data: p }))
  })

  it('open by default; fold and unfold persist in this browser only', async () => {
    const { guide } = await setup()
    expect(guide.folded).toBe(false)
    guide.setFolded(true)
    expect(guide.folded).toBe(true)
    expect(h.patch).not.toHaveBeenCalled()
    const keys = [...mem.keys()]
    expect(keys.some((k) => k.startsWith('giljo_banner_dismissals_u-1'))).toBe(true)
    expect(mem.get(keys.find((k) => k.startsWith('giljo_banner_dismissals_u-1')))).toContain('guide:folded')
    setActivePinia(createPinia())
    useUserStore().currentUser = { id: 'u-1', created_at: AFTER, guide_closed: false, intro_video_seen: true }
    expect(useGuideStore().folded).toBe(true)
    useGuideStore().setFolded(false)
    expect(useGuideStore().folded).toBe(false)
  })
})

describe('guide pane: the connect pop-up opens once, by itself, for a person with no tool', () => {
  beforeEach(() => {
    installMemoryStorage()
    h.patch.mockReset()
    h.patch.mockImplementation(async (p) => ({ data: p }))
  })

  const router = () => ({ push: vi.fn() })

  it('no tool connected: opens it through the existing home?openSetup mechanism, once', async () => {
    const { guide } = await setup()
    const r = router()
    expect(await guide.offerConnectOnce(r)).toBe(true)
    expect(r.push).toHaveBeenCalledWith({ path: '/home', query: { openSetup: 'true' } })
    expect(await guide.offerConnectOnce(r)).toBe(false)
    expect(r.push).toHaveBeenCalledTimes(1)
    setActivePinia(createPinia())
    h.list = startListPayload()
    useUserStore().currentUser = { id: 'u-1', created_at: AFTER, guide_closed: false, intro_video_seen: true }
    expect(await useGuideStore().offerConnectOnce(r)).toBe(false)
    expect(r.push).toHaveBeenCalledTimes(1)
  })

  it('a tool already connected: never', async () => {
    const { guide } = await setup({
      list: startListPayload({ tool_connected: { done: true, live: true, tool_name: 'Claude' } }),
    })
    const r = router()
    expect(await guide.offerConnectOnce(r)).toBe(false)
    expect(r.push).not.toHaveBeenCalled()
  })

  it('connected before but not live counts as a tool: never', async () => {
    const { guide } = await setup({
      list: startListPayload({ tool_connected: { done: true, live: false } }),
    })
    const r = router()
    expect(await guide.offerConnectOnce(r)).toBe(false)
  })

  it('reads fresh facts first: a tool connected while the video played is respected', async () => {
    const { guide } = await setup()
    h.list = startListPayload({ tool_connected: { done: true, live: true, tool_name: 'Claude' } })
    const r = router()
    expect(await guide.offerConnectOnce(r)).toBe(false)
    expect(r.push).not.toHaveBeenCalled()
  })

  it('an unreadable list opens nothing and uses up nothing', async () => {
    setActivePinia(createPinia())
    h.list = { nope: true }
    useUserStore().currentUser = { id: 'u-1', created_at: AFTER, guide_closed: false, intro_video_seen: true }
    const guide = useGuideStore()
    const r = router()
    expect(await guide.offerConnectOnce(r)).toBe(false)
    h.list = startListPayload()
    expect(await guide.offerConnectOnce(r)).toBe(true)
  })
})
