// Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
// Licensed under the Elastic License 2.0.
// See LICENSE in the project root for terms.
// [CE] Community Edition.

/**
 * bannerDismissStore.js — FE-9589
 *
 * Per-user, reload-surviving dismissal state for the banner rows whose
 * VISIBILITY is a live read of server state (the raised hand, the thread-post
 * row, the Hub baton). Those rows are not notifications, so there is no
 * `markDismissed` row to write; and they are not ephemeral like the lifecycle
 * rows, so in-memory dismissal would come straight back on the next page load.
 * A banner that returns on refresh was hidden, not dismissed.
 *
 * WHAT A DISMISSAL IS. It silences the ANNOUNCEMENT and nothing else. No
 * server state is touched: the approval stays pending, the baton stays yours,
 * the mention stays unread, and every one of them stays reachable from the Hub
 * and the bell. This store is the operator saying "I have seen this strip",
 * never "this work is done".
 *
 * KEYS CARRY THE OBLIGATION'S IDENTITY, so a NEW obligation still announces
 * itself: an approval key is its approval id, a mention key names the newest
 * naming post, a baton key names the post that handed it over. A key that
 * cannot change on its own (a directed ask, which the attention projection
 * reports per thread with no post id) is instead RECONCILED away the moment
 * the projection says it is no longer live -- see `reconcile`.
 *
 * WHERE IT LIVES: localStorage under a per-user key, on the FE-9241 precedent
 * in stores/notifications.js (same reasoning, same failure it avoids -- one
 * browser profile shared by two logins must not inherit the other's
 * dismissals). Not a server table: this is a per-viewer display preference,
 * and giving it a migration would make a UI acknowledgement durable across
 * devices, which nobody asked for.
 *
 * Edition Scope: Both
 */
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import { useUserStore } from '@/stores/user'

const STORAGE_KEY_PREFIX = 'giljo_banner_dismissals'

/** Bound the persisted set so a chatty tenant cannot grow localStorage forever. */
const MAX_DISMISSED_KEYS = 200

function storageKey(userId) {
  return `${STORAGE_KEY_PREFIX}_${userId}`
}

/** Read this user's dismissed keys. Never throws -- a broken/absent store means none. */
function loadKeys(userId) {
  if (!userId) return []
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey(userId)) ?? 'null')
    return Array.isArray(parsed) ? parsed.filter((k) => typeof k === 'string') : []
  } catch {
    return []
  }
}

/** Write this user's dismissed keys, newest-last and capped. Never throws. */
function saveKeys(keys, userId) {
  if (!userId) return
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify(keys.slice(-MAX_DISMISSED_KEYS)))
  } catch {
    // localStorage unavailable or full -- non-fatal, the in-memory set still holds.
  }
}

export const useBannerDismissStore = defineStore('bannerDismiss', () => {
  /** Insertion-ordered so the cap above evicts the OLDEST dismissal, not a random one. */
  const keys = ref([])
  const keySet = computed(() => new Set(keys.value))

  const userStore = useUserStore()
  const currentUserId = computed(() => userStore.currentUser?.id ?? null)

  // Hydrate on the user we actually have, and re-hydrate if it changes: a second
  // login in the same browser profile must not read the first one's dismissals.
  watch(
    currentUserId,
    (userId) => {
      keys.value = loadKeys(userId)
    },
    { immediate: true },
  )

  function isDismissed(key) {
    return Boolean(key) && keySet.value.has(key)
  }

  /** Dismiss one or more keys. Already-dismissed keys keep their original position. */
  function dismiss(input) {
    const incoming = (Array.isArray(input) ? input : [input]).filter(Boolean)
    if (!incoming.length) return
    const existing = keySet.value
    const added = incoming.filter((k) => !existing.has(k))
    if (!added.length) return
    keys.value = [...keys.value, ...added].slice(-MAX_DISMISSED_KEYS)
    saveKeys(keys.value, currentUserId.value)
  }

  /**
   * Drop stored keys in one family that are no longer live.
   *
   * This is what lets a dismissed row come BACK when the same obligation
   * recurs under a key that cannot change (see the docblock). Callers must only
   * pass a `liveKeys` set they know is hydrated -- an unloaded read looks
   * exactly like "nothing is waiting", and reconciling against that would
   * un-dismiss the whole family on every cold page load.
   */
  function reconcile(prefix, liveKeys) {
    const live = liveKeys instanceof Set ? liveKeys : new Set(liveKeys || [])
    const kept = keys.value.filter((k) => !k.startsWith(prefix) || live.has(k))
    if (kept.length === keys.value.length) return
    keys.value = kept
    saveKeys(keys.value, currentUserId.value)
  }

  /**
   * Logout: forget this browser's dismissals so the next account on it does not
   * inherit them.
   *
   * `userId` is accepted explicitly because the logout flow nulls `currentUser`
   * before the dependent stores are cleaned up -- the FE-9241 reason
   * notificationStore.clearAll() takes one too. Callers with a live session
   * (tests, a manual reset) may omit it.
   */
  function clear(userId) {
    keys.value = []
    const owner = userId ?? currentUserId.value
    if (!owner) return
    try {
      localStorage.removeItem(storageKey(owner))
    } catch {
      // localStorage unavailable -- the in-memory set is already empty.
    }
  }

  return { keys, isDismissed, dismiss, reconcile, clear }
})
