// Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
// Licensed under the Elastic License 2.0.
// See LICENSE in the project root for terms.
// [CE] Community Edition.

import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import { useUserStore } from '@/stores/user'

const STORAGE_KEY_PREFIX = 'giljo_banner_dismissals'

const MAX_DISMISSED_KEYS = 200

function storageKey(userId) {
  return `${STORAGE_KEY_PREFIX}_${userId}`
}

function loadKeys(userId) {
  if (!userId) return []
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey(userId)) ?? 'null')
    return Array.isArray(parsed) ? parsed.filter((k) => typeof k === 'string') : []
  } catch {
    return []
  }
}

function saveKeys(keys, userId) {
  if (!userId) return
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify(keys.slice(-MAX_DISMISSED_KEYS)))
  } catch {
    // localStorage unavailable or full -- non-fatal, the in-memory set still holds.
  }
}

export const useBannerDismissStore = defineStore('bannerDismiss', () => {
  const keys = ref([])
  const keySet = computed(() => new Set(keys.value))

  const userStore = useUserStore()
  const currentUserId = computed(() => userStore.currentUser?.id ?? null)

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

  function dismiss(input) {
    const incoming = (Array.isArray(input) ? input : [input]).filter(Boolean)
    if (!incoming.length) return
    const existing = keySet.value
    const added = incoming.filter((k) => !existing.has(k))
    if (!added.length) return
    keys.value = [...keys.value, ...added].slice(-MAX_DISMISSED_KEYS)
    saveKeys(keys.value, currentUserId.value)
  }

  function reconcile(prefix, liveKeys) {
    const live = liveKeys instanceof Set ? liveKeys : new Set(liveKeys || [])
    const kept = keys.value.filter((k) => !k.startsWith(prefix) || live.has(k))
    if (kept.length === keys.value.length) return
    keys.value = kept
    saveKeys(keys.value, currentUserId.value)
  }

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
