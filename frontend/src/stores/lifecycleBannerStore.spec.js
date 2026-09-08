// Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
// Licensed under the Elastic License 2.0.
// See LICENSE in the project root for terms.
// [CE] Community Edition.

/**
 * lifecycleBannerStore.spec.js — FE-9538
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useLifecycleBannerStore, MAX_LIFECYCLE_ROWS } from './lifecycleBannerStore'
import { useProjectStore } from '@/stores/projects'

beforeEach(() => {
  setActivePinia(createPinia())
})

function seedProject(id, overrides = {}) {
  // projectById() falls back to the trimmed list row (projects.js:61) when an
  // entity has only been seen in a list fetch -- no public single-row writer
  // exists on this store, so this is the same fallback path any list-fetched
  // project takes.
  useProjectStore().projects.push({
    id,
    name: 'Fix the thing',
    taxonomy_alias: 'BE-1234',
    ...overrides,
  })
}

describe('useLifecycleBannerStore', () => {
  it('announce() adds a row carrying the project taxonomy + title from projectStore', () => {
    seedProject('p1')
    const store = useLifecycleBannerStore()
    store.announce({ projectId: 'p1', moment: 'staging_complete' })
    expect(store.rows).toHaveLength(1)
    expect(store.rows[0]).toMatchObject({
      projectId: 'p1',
      moment: 'staging_complete',
      taxonomyAlias: 'BE-1234',
      title: 'Fix the thing',
    })
  })

  it('degrades gracefully when the project was never opened this session (cache miss)', () => {
    const store = useLifecycleBannerStore()
    store.announce({ projectId: 'p-unseen', moment: 'implementation_launched' })
    expect(store.rows).toHaveLength(1)
    expect(store.rows[0].taxonomyAlias).toBeNull()
    expect(store.rows[0].title).toBeNull()
  })

  it('ignores an unrecognized moment rather than crashing the banner', () => {
    seedProject('p1')
    const store = useLifecycleBannerStore()
    store.announce({ projectId: 'p1', moment: 'not_a_real_moment' })
    expect(store.rows).toHaveLength(0)
  })

  it('ignores a call with no projectId', () => {
    const store = useLifecycleBannerStore()
    store.announce({ projectId: null, moment: 'activated' })
    expect(store.rows).toHaveLength(0)
  })

  it('a project moving through TWO moments replaces its row rather than stacking', () => {
    seedProject('p1')
    const store = useLifecycleBannerStore()
    store.announce({ projectId: 'p1', moment: 'staging_complete' })
    store.announce({ projectId: 'p1', moment: 'implementation_launched' })
    expect(store.rows).toHaveLength(1)
    expect(store.rows[0].moment).toBe('implementation_launched')
  })

  it('caps at MAX_LIFECYCLE_ROWS, newest first, oldest dropped', () => {
    const store = useLifecycleBannerStore()
    for (let i = 0; i < MAX_LIFECYCLE_ROWS + 2; i++) {
      seedProject(`p${i}`)
      store.announce({ projectId: `p${i}`, moment: 'activated' })
    }
    expect(store.rows).toHaveLength(MAX_LIFECYCLE_ROWS)
    // Newest announced project is first.
    expect(store.rows[0].projectId).toBe(`p${MAX_LIFECYCLE_ROWS + 1}`)
  })

  it('dismiss() removes exactly the named row', () => {
    seedProject('p1')
    seedProject('p2')
    const store = useLifecycleBannerStore()
    store.announce({ projectId: 'p1', moment: 'staging_complete' })
    store.announce({ projectId: 'p2', moment: 'activated' })
    const idToRemove = store.rows.find((r) => r.projectId === 'p1').id
    store.dismiss(idToRemove)
    expect(store.rows).toHaveLength(1)
    expect(store.rows[0].projectId).toBe('p2')
  })

  it('momentLabel() returns canned copy per moment, and a safe fallback for unknown', () => {
    const store = useLifecycleBannerStore()
    expect(store.momentLabel('staging_complete')).toBe('is ready to launch')
    expect(store.momentLabel('activated')).toBe('has started')
    expect(store.momentLabel('implementation_launched')).toBe('has started implementation')
    expect(store.momentLabel('garbage')).toBe('has updated')
  })
})
