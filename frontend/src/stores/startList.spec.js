import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ calls: 0, impl: null }))
vi.mock('@/services/api', () => ({
  default: {
    onboarding: {
      startList: vi.fn(() => {
        h.calls += 1
        return h.impl()
      }),
    },
  },
}))
vi.mock('@/stores/user', () => ({ useUserStore: () => ({ currentUser: { id: 'u-1' } }) }))

import { useStartListStore } from '@/stores/startList'
import { startListPayload, ALL_DONE } from '../../tests/helpers/startListRows'

const payload = (done = []) => {
  const keys = ['tool_connected', 'skills_installed', 'product_exists', 'project_created', 'project_staged', 'project_built']
  return {
    data: startListPayload(Object.fromEntries(keys.map((k, i) => [k, done.includes(i + 1) ? { done: true } : {}]))),
  }
}

describe('useStartListStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.calls = 0
    h.impl = async () => payload([1])
  })

  it('is not loaded before the first read, and loaded after', async () => {
    const s = useStartListStore()
    expect(s.loaded).toBe(false)
    await s.refresh()
    expect(s.loaded).toBe(true)
    expect(s.doneCount).toBe(1)
    expect(s.rows.tool_connected.done).toBe(true)
  })

  it('a failed first read leaves it not loaded and does not throw', async () => {
    h.impl = async () => {
      throw new Error('boom')
    }
    const s = useStartListStore()
    await expect(s.refresh()).resolves.toBeUndefined()
    expect(s.loaded).toBe(false)
  })

  it('a synchronous throw from the api call also leaves it usable for the next read', async () => {
    h.impl = () => {
      throw new Error('sync')
    }
    const s = useStartListStore()
    await s.refresh()
    h.impl = async () => payload([1, 2])
    await s.refresh()
    expect(s.doneCount).toBe(2)
  })

  it('a failed later read keeps the last known state', async () => {
    const s = useStartListStore()
    await s.refresh()
    h.impl = async () => {
      throw new Error('boom')
    }
    await s.refresh()
    expect(s.doneCount).toBe(1)
    expect(s.loaded).toBe(true)
  })

  it('a reply of the wrong shape is a failed read', async () => {
    const s = useStartListStore()
    h.impl = async () => ({ data: { rows: { tool_connected: { done: true } }, done_count: 1 } })
    await s.refresh()
    expect(s.loaded).toBe(false)
  })

  it('two plain reads in flight share one request; a forced read during a flight re-reads once afterwards', async () => {
    const s = useStartListStore()
    let release
    h.impl = () => new Promise((r) => (release = () => r(payload([1]))))
    const a = s.refresh()
    const b = s.refresh()
    expect(h.calls).toBe(1)
    s.refresh({ force: true })
    const second = vi.fn(async () => payload([1, 2, 3]))
    h.impl = second
    release()
    await Promise.resolve()
    await Promise.resolve()
    h.impl = async () => payload([1, 2, 3])
    await a
    await b
    await s.refresh()
    expect(s.doneCount).toBe(3)
    expect(h.calls).toBeGreaterThanOrEqual(2)
  })

  it('has six steps; all done only at six', async () => {
    const s = useStartListStore()
    expect(s.stepCount).toBe(6)
    h.impl = async () => payload([1, 2, 3, 4, 5])
    await s.refresh()
    expect(s.doneCount).toBe(5)
    expect(s.allDone).toBe(false)
    h.impl = async () => ({ data: ALL_DONE })
    await s.refresh({ force: true })
    expect(s.allDone).toBe(true)
  })

  it('carries the new facts: project_created, the staged mode, in_progress', async () => {
    h.impl = async () => ({
      data: startListPayload({
        project_created: { done: true, project_id: 'p-7', project_name: 'Add a search box' },
        project_staged: { done: true, mode: 'multi_terminal' },
        project_built: { in_progress: true },
      }),
    })
    const s = useStartListStore()
    await s.refresh()
    expect(s.rows.project_created.project_id).toBe('p-7')
    expect(s.rows.project_staged.mode).toBe('multi_terminal')
    expect(s.rows.project_built.in_progress).toBe(true)
  })

  it('an answer from a server that has no project_created yet still loads, as not done', async () => {
    const old = startListPayload()
    delete old.rows.project_created
    h.impl = async () => ({ data: old })
    const s = useStartListStore()
    await s.refresh()
    expect(s.loaded).toBe(true)
    expect(s.rows.project_created.done).toBe(false)
  })
})
