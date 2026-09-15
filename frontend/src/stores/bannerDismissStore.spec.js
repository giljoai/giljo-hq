import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useBannerDismissStore } from './bannerDismissStore'
import { useUserStore } from './user'

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

function freshStore(userId) {
  setActivePinia(createPinia())
  useUserStore().currentUser = userId ? { id: userId } : null
  return useBannerDismissStore()
}

describe('bannerDismissStore (FE-9589)', () => {
  beforeEach(() => {
    installFunctionalLocalStorage()
  })

  it('rehydrates a dismissal for the same user', () => {
    freshStore('user-a').dismiss('approval:appr-1')

    expect(freshStore('user-a').isDismissed('approval:appr-1')).toBe(true)
  })

  it('does NOT leak dismissals between users sharing a browser profile', () => {
    freshStore('user-a').dismiss('approval:appr-1')

    expect(freshStore('user-b').isDismissed('approval:appr-1')).toBe(false)
  })

  it('holds nothing at all when there is no authenticated user', () => {
    const store = freshStore(null)
    store.dismiss('approval:appr-1')

    expect(store.isDismissed('approval:appr-1')).toBe(true)
    expect(freshStore('user-a').isDismissed('approval:appr-1')).toBe(false)
  })

  it('reconciles away a key its family no longer reports', () => {
    const store = freshStore('user-a')
    store.dismiss(['ask:t-1', 'ask:t-2', 'mention:t-9:m-1'])

    store.reconcile('ask:', new Set(['ask:t-2']))

    expect(store.isDismissed('ask:t-1')).toBe(false)
    expect(store.isDismissed('ask:t-2')).toBe(true)
    expect(store.isDismissed('mention:t-9:m-1')).toBe(true)
  })

  it('persists a reconcile, so a dropped key does not come back on reload', () => {
    freshStore('user-a').dismiss('ask:t-1')
    const store = freshStore('user-a')
    store.reconcile('ask:', new Set())

    expect(freshStore('user-a').isDismissed('ask:t-1')).toBe(false)
  })

  it('clear() empties the set and the stored copy', () => {
    const store = freshStore('user-a')
    store.dismiss('approval:appr-1')
    store.clear()

    expect(store.isDismissed('approval:appr-1')).toBe(false)
    expect(freshStore('user-a').isDismissed('approval:appr-1')).toBe(false)
  })

  it('clear(outgoingUserId) works after the session has already been nulled', () => {
    const store = freshStore('user-a')
    store.dismiss('approval:appr-1')
    useUserStore().currentUser = null

    store.clear('user-a')

    expect(freshStore('user-a').isDismissed('approval:appr-1')).toBe(false)
  })
})
