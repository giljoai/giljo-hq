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
