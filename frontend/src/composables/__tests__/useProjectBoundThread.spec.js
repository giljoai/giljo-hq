import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useProjectBoundThread } from '@/composables/useProjectBoundThread'
import { useCommHubStore } from '@/stores/commHubStore'

const P = 'proj-bound'

describe('useProjectBoundThread.resolveExistingProjectThread (deterministic, no-create)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useCommHubStore()
    vi.spyOn(store, 'loadThreads').mockResolvedValue(undefined)
    vi.spyOn(store, 'createThread').mockResolvedValue(undefined)
  })

  it('returns null and NEVER creates when the project has no bound thread', async () => {
    const { resolveExistingProjectThread } = useProjectBoundThread()
    const t = await resolveExistingProjectThread(P)
    expect(t).toBeNull()
    expect(store.createThread).not.toHaveBeenCalled()
  })

  it('returns the sole candidate', async () => {
    store._testSeedThread({ thread_id: 'only', project_id: P, subject: 'whatever', created_at: '2026-06-01T00:00:00Z' })
    const { resolveExistingProjectThread } = useProjectBoundThread()
    const t = await resolveExistingProjectThread(P)
    expect(t.thread_id).toBe('only')
    expect(store.createThread).not.toHaveBeenCalled()
  })

  it('prefers the (project comms)-marker thread when several exist', async () => {
    store._testSeedThread({ thread_id: 'plain', project_id: P, subject: 'chatter', created_at: '2026-06-01T00:00:00Z' })
    store._testSeedThread({ thread_id: 'marked', project_id: P, subject: '(project comms)', created_at: '2026-06-05T00:00:00Z' })
    const { resolveExistingProjectThread } = useProjectBoundThread()
    const t = await resolveExistingProjectThread(P)
    expect(t.thread_id).toBe('marked')
  })

  it('falls back to the OLDEST by created_at when several exist without the marker', async () => {
    store._testSeedThread({ thread_id: 'newer', project_id: P, subject: 'a', created_at: '2026-06-10T00:00:00Z' })
    store._testSeedThread({ thread_id: 'older', project_id: P, subject: 'b', created_at: '2026-06-01T00:00:00Z' })
    const { resolveExistingProjectThread } = useProjectBoundThread()
    const t = await resolveExistingProjectThread(P)
    expect(t.thread_id).toBe('older')
  })

  it('ignores threads belonging to other projects', async () => {
    store._testSeedThread({ thread_id: 'mine', project_id: P, subject: 'x', created_at: '2026-06-01T00:00:00Z' })
    store._testSeedThread({ thread_id: 'other', project_id: 'proj-other', subject: 'y', created_at: '2026-05-01T00:00:00Z' })
    const { resolveExistingProjectThread } = useProjectBoundThread()
    const t = await resolveExistingProjectThread(P)
    expect(t.thread_id).toBe('mine')
  })
})
