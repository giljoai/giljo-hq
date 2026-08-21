/**
 * projectTabs.spec.js — TSK-9372
 *
 * $reset coverage: after mutating state, every state field returns to its
 * initial value. $reset clears state between sessions and on logout; a
 * silently broken one leaks a previous session's project into the next view.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useProjectTabsStore } from './projectTabs'

describe('projectTabs — $reset (TSK-9372)', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useProjectTabsStore()
  })

  it('$reset restores currentProject and isLaunched to initial values', () => {
    store.setCurrentProject({ id: 'proj-1', name: 'Previous session project' })
    store.setLaunched(true)
    expect(store.currentProject).not.toBeNull()
    expect(store.isLaunched).toBe(true)

    store.$reset()

    expect(store.currentProject).toBeNull()
    expect(store.isLaunched).toBe(false)
  })
})
