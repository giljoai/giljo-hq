import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import { immutableMapSet, immutableMapDelete, immutableObjectPatch } from './immutableHelpers'
import api from '@/services/api'
import { useThreadPostAttention } from '@/composables/useThreadPostAttention'
import { useUserStore } from '@/stores/user'
import { useProductStore } from '@/stores/products'


function normalizeMessage(raw) {
  if (!raw) return null
  const id = raw.message_id || raw.id
  if (!id) return null
  return {
    message_id: id,
    thread_id: raw.thread_id || null,
    from_agent_id: raw.from_agent_id || null,
    from_display_name: raw.from_display_name || raw.from_agent_id || 'unknown',
    from_kind: raw.from_kind || 'agent',
    content: raw.content || '',
    message_type: raw.message_type || 'broadcast',
    priority: raw.priority || 'normal',
    status: raw.status || null,
    requires_action: raw.requires_action || false,
    created_at: raw.created_at || null,
    recipients: Array.isArray(raw.recipients) ? raw.recipients : null,
    acked_by: Array.isArray(raw.acked_by) ? raw.acked_by : null,
    completed_by: Array.isArray(raw.completed_by) ? raw.completed_by : null,
    pending_for: Array.isArray(raw.pending_for) ? raw.pending_for : null,
  }
}

function normalizeThread(raw) {
  if (!raw) return null
  const id = raw.thread_id || raw.id
  if (!id) return null
  return {
    thread_id: id,
    chat_id: raw.chat_id || null,
    subject: raw.subject || null,
    status: raw.status || 'open',
    next_action_owner: raw.next_action_owner || null,
    severity: raw.severity || null,
    product_id: raw.product_id || null,
    project_id: raw.project_id || null,
    project_ids: Array.isArray(raw.project_ids) ? raw.project_ids : raw.project_id ? [raw.project_id] : [],
    created_at: raw.created_at || null,
    last_activity_at: raw.updated_at || raw.last_activity_at || raw.created_at || null,
    ...('title' in raw ? { title: raw.title || null } : {}),
    ...('project_name' in raw ? { project_name: raw.project_name || null } : {}),
    ...('participants' in raw ? { participants: Array.isArray(raw.participants) ? raw.participants : [] } : {}),
    ...('last_message' in raw ? { last_message: raw.last_message || null } : {}),
    ...('unread' in raw ? { unread: !!raw.unread } : {}),
  }
}


function refreshThreadPostAttention() {
  return useThreadPostAttention().refresh()
}

export const useCommHubStore = defineStore('commHub', () => {
  const threadsById = ref(new Map())
  const messagesByThreadId = ref(new Map())
  const participantsByThreadId = ref(new Map())
  const selectedThreadId = ref(null)
  const unreadByThreadId = ref(new Map())
  const filters = ref({
    status: null,
    owner: null,
    product_id: null,
    project_id: null,
  })
  const productScope = ref('viewed')
  const loading = ref(false)
  const error = ref(null)
  const _hydratingThreadIds = new Set()
  const _rehydrateWantedThreadIds = new Set()


  const threadList = computed(() => {
    const viewedProductId = useProductStore().currentProductId
    const all = Array.from(threadsById.value.values())
    let arr
    if (productScope.value === 'unassigned') {
      arr = all.filter((t) => t.product_id == null)
    } else if (productScope.value === 'all' || !viewedProductId) {
      arr = all
    } else {
      arr = all.filter((t) => t.product_id === viewedProductId)
    }
    arr = [...arr]
    arr.sort((a, b) => {
      const ta = a.last_activity_at ? new Date(a.last_activity_at).getTime() : 0
      const tb = b.last_activity_at ? new Date(b.last_activity_at).getTime() : 0
      return tb - ta
    })
    return arr
  })

  function setProductScope(scope) {
    if (!['viewed', 'all', 'unassigned'].includes(scope)) return
    productScope.value = scope
  }


  const projectThreadList = computed(() => threadList.value.filter((t) => t.project_id != null))

  const townSquareThreadList = computed(() => threadList.value.filter((t) => t.project_id == null))

  const projectUnreadTotal = computed(() =>
    projectThreadList.value.reduce((sum, t) => sum + unreadFor(t.thread_id), 0),
  )
  const townSquareUnreadTotal = computed(() =>
    townSquareThreadList.value.reduce((sum, t) => sum + unreadFor(t.thread_id), 0),
  )

  function messagesFor(threadId) {
    return messagesByThreadId.value.get(threadId) || []
  }

  function participantsFor(threadId) {
    return participantsByThreadId.value.get(threadId) || []
  }

  const selectedThread = computed(() => {
    if (!selectedThreadId.value) return null
    return threadsById.value.get(selectedThreadId.value) || null
  })


  function unreadFor(threadId) {
    return unreadByThreadId.value.get(threadId) || 0
  }

  const totalUnread = computed(() => {
    let sum = 0
    for (const count of unreadByThreadId.value.values()) {
      sum += count
    }
    return sum
  })

  const batonThreadIds = computed(() => {
    const userId = useUserStore().currentUser?.id
    if (!userId) return []
    const ids = []
    for (const thread of threadsById.value.values()) {
      if (thread.next_action_owner === userId) ids.push(thread.thread_id)
    }
    return ids
  })

  const yourTurnCount = computed(() => batonThreadIds.value.length)

  const hasUserAttention = computed(() => totalUnread.value > 0 || yourTurnCount.value > 0)


  function _upsertThread(raw) {
    const thread = normalizeThread(raw)
    if (!thread) return
    const existing = threadsById.value.get(thread.thread_id)
    if (existing) {
      const patched = immutableObjectPatch(existing, thread)
      if (JSON.stringify(existing) === JSON.stringify(patched)) return
      threadsById.value = immutableMapSet(threadsById.value, thread.thread_id, patched)
    } else {
      threadsById.value = immutableMapSet(threadsById.value, thread.thread_id, thread)
    }
  }

  function _upsertMessage(threadId, rawMessage) {
    const message = normalizeMessage(rawMessage)
    if (!message || !threadId) return

    const previousList = messagesByThreadId.value.get(threadId) || []
    const existingIndex = previousList.findIndex((m) => m.message_id === message.message_id)

    if (existingIndex === -1) {
      const nextList = [...previousList, message]
      messagesByThreadId.value = immutableMapSet(messagesByThreadId.value, threadId, nextList)
      return
    }

    const previousMessage = previousList[existingIndex]
    const nextMessage = immutableObjectPatch(previousMessage, message)
    if (JSON.stringify(previousMessage) === JSON.stringify(nextMessage)) return

    const nextList = [...previousList]
    nextList[existingIndex] = nextMessage
    messagesByThreadId.value = immutableMapSet(messagesByThreadId.value, threadId, nextList)
  }


  async function loadThreads(filterOverride) {
    loading.value = true
    error.value = null
    try {
      const params = { ...(filterOverride ?? filters.value) }
      if (params.product_id == null && productScope.value === 'viewed') {
        const productStore = useProductStore()
        if (productStore.currentProductId) params.product_id = productStore.currentProductId
      }
      Object.keys(params).forEach((k) => {
        if (params[k] == null) delete params[k]
      })
      const res = await api.threads.list(params)
      const threads = res.data?.threads || []
      threads.forEach((t) => _upsertThread(t))
    } catch (err) {
      error.value = err?.message || 'Failed to load threads'
    } finally {
      loading.value = false
    }
  }

  async function loadThread(id) {
    loading.value = true
    error.value = null
    try {
      const res = await api.threads.history(id)
      const thread = res.data?.thread
      const messages = res.data?.messages || []
      if (thread) _upsertThread(thread)
      const normalized = messages
        .map((m) => normalizeMessage(m))
        .filter(Boolean)
        .reduce((acc, m) => {
          if (!acc.find((x) => x.message_id === m.message_id)) acc.push(m)
          return acc
        }, [])
      messagesByThreadId.value = immutableMapSet(messagesByThreadId.value, id, normalized)
      markThreadRead(id)
    } catch (err) {
      error.value = err?.message || 'Failed to load thread'
    } finally {
      loading.value = false
    }
  }

  async function loadParticipants(id) {
    try {
      const res = await api.threads.participants(id)
      const participants = res.data?.participants || []
      participantsByThreadId.value = immutableMapSet(
        participantsByThreadId.value,
        id,
        participants,
      )
    } catch (err) {
      error.value = err?.message || 'Failed to load participants'
    }
  }

  async function createThread(body) {
    const res = await api.threads.create(body)
    const thread = res.data
    if (thread) _upsertThread(thread)
    return thread
  }

  function refusalToError(data) {
    const err = new Error(data.hint || data.error || 'The server declined this request.')
    err.refusal = data
    return err
  }

  function isRefusal(data) {
    return data?.success === false
  }

  async function postMessage(id, body) {
    const res = await api.threads.post(id, body)
    const data = res.data
    if (isRefusal(data)) throw refusalToError(data)
    if (data?.baton_passed || data?.baton_cleared) {
      const existing = threadsById.value.get(id)
      if (existing) {
        threadsById.value = immutableMapSet(
          threadsById.value,
          id,
          immutableObjectPatch(existing, { next_action_owner: data.next_action_owner }),
        )
      }
    }
    return data
  }

  async function passBaton(id, to) {
    const res = await api.threads.passBaton(id, to)
    const updated = res.data
    if (isRefusal(updated)) throw refusalToError(updated)
    if (updated?.thread_id) {
      const existing = threadsById.value.get(updated.thread_id)
      if (existing) {
        threadsById.value = immutableMapSet(
          threadsById.value,
          updated.thread_id,
          immutableObjectPatch(existing, { next_action_owner: updated.next_action_owner }),
        )
      }
    }
    return updated
  }

  async function renameThread(id, subject) {
    const res = await api.threads.update(id, { subject })
    const updated = res.data
    const existing = threadsById.value.get(id)
    if (existing && updated) {
      const patch = { subject: updated.subject ?? subject }
      if ('title' in updated) patch.title = updated.title
      threadsById.value = immutableMapSet(threadsById.value, id, immutableObjectPatch(existing, patch))
    }
    return updated
  }

  async function retagThread(id, { productId, projectIds } = {}) {
    const body = {}
    if (productId === '') body.clear_product = true
    else if (productId != null) body.product_id = productId
    if (projectIds != null) body.project_ids = projectIds
    if (Object.keys(body).length === 0) return threadsById.value.get(id) || null

    const res = await api.threads.update(id, body)
    const updated = res.data
    const existing = threadsById.value.get(id)
    if (existing && updated) {
      const patch = {}
      if ('product_id' in updated) patch.product_id = updated.product_id
      if ('project_ids' in updated) patch.project_ids = updated.project_ids
      threadsById.value = immutableMapSet(threadsById.value, id, immutableObjectPatch(existing, patch))
    }
    return updated
  }

  async function deleteThread(id) {
    if (!id) return
    await api.threads.delete(id)
    _removeThreadLocal(id)
  }

  function _removeThreadLocal(id) {
    threadsById.value = immutableMapDelete(threadsById.value, id)
    messagesByThreadId.value = immutableMapDelete(messagesByThreadId.value, id)
    participantsByThreadId.value = immutableMapDelete(participantsByThreadId.value, id)
    unreadByThreadId.value = immutableMapDelete(unreadByThreadId.value, id)
    if (selectedThreadId.value === id) selectedThreadId.value = null
  }

  async function searchThreads(query) {
    loading.value = true
    error.value = null
    try {
      const res = await api.threads.search({ query })
      const threads = res.data?.threads || []
      threads.forEach((t) => _upsertThread(t))
      return threads
    } catch (err) {
      error.value = err?.message || 'Search failed'
      return []
    } finally {
      loading.value = false
    }
  }

  function markThreadRead(threadId) {
    if (!threadId) return
    if ((unreadByThreadId.value.get(threadId) || 0) === 0) return
    unreadByThreadId.value = immutableMapSet(unreadByThreadId.value, threadId, 0)
  }

  async function markThreadsRead(ids) {
    const unique = [...new Set((ids || []).filter(Boolean))]
    if (!unique.length) return
    unique.forEach(markThreadRead)
    await Promise.allSettled(unique.map((id) => api.threads.markRead(id)))
    refreshThreadPostAttention()
  }

  function selectThread(id) {
    selectedThreadId.value = id
    markThreadRead(id)
    if (id) {
      api.threads
        .markRead(id)
        .then(() => refreshThreadPostAttention())
        .catch(() => {})
    }
  }


  async function handleThreadMessage(payload) {
    const threadId = payload?.thread_id
    if (!threadId) return
    _upsertMessage(threadId, payload)
    const existing = threadsById.value.get(threadId)
    if (existing && payload.created_at) {
      threadsById.value = immutableMapSet(
        threadsById.value,
        threadId,
        immutableObjectPatch(existing, { last_activity_at: payload.created_at }),
      )
    }
    if (threadId !== selectedThreadId.value) {
      const prev = unreadByThreadId.value.get(threadId) || 0
      unreadByThreadId.value = immutableMapSet(unreadByThreadId.value, threadId, prev + 1)
    }

    if (payload.content_truncated) {
      await hydrateThreadMessages(threadId)
    }
  }

  async function hydrateThreadMessages(threadId) {
    if (!threadId) return
    if (_hydratingThreadIds.has(threadId)) {
      _rehydrateWantedThreadIds.add(threadId)
      return
    }
    _hydratingThreadIds.add(threadId)
    try {
      do {
        _rehydrateWantedThreadIds.delete(threadId)
        const res = await api.threads.history(threadId)
        const messages = res.data?.messages || []
        messages.forEach((m) => _upsertMessage(threadId, m))
      } while (_rehydrateWantedThreadIds.has(threadId))
    } catch {
      // Best-effort: the excerpt stays on screen and the next open re-reads the
      // thread in full. A failed top-up must never blank a message the operator
      // can already partly read.
    } finally {
      _hydratingThreadIds.delete(threadId)
      _rehydrateWantedThreadIds.delete(threadId)
    }
  }

  function handleThreadUpdate(payload) {
    const threadId = payload?.thread_id
    if (!threadId) return

    if (payload.update_type === 'deleted') {
      _removeThreadLocal(threadId)
      return
    }

    if (payload.update_type === 'created' && !threadsById.value.has(threadId)) {
      loadThreads(filters.value)
      return
    }

    if (payload.update_type === 'restored' && !threadsById.value.has(threadId)) {
      loadThreads(filters.value)
      return
    }

    const existing = threadsById.value.get(threadId)
    if (!existing) return

    const patch = {}
    if (payload.status != null) patch.status = payload.status
    if (payload.next_action_owner != null) patch.next_action_owner = payload.next_action_owner
    if (payload.chat_id != null) patch.chat_id = payload.chat_id
    if (payload.subject != null) patch.subject = payload.subject

    if (Object.keys(patch).length === 0) return
    const updated = immutableObjectPatch(existing, patch)
    if (JSON.stringify(existing) === JSON.stringify(updated)) return
    threadsById.value = immutableMapSet(threadsById.value, threadId, updated)
  }


  function $reset() {
    threadsById.value = new Map()
    messagesByThreadId.value = new Map()
    participantsByThreadId.value = new Map()
    unreadByThreadId.value = new Map()
    selectedThreadId.value = null
    filters.value = { status: null, owner: null, product_id: null, project_id: null }
    productScope.value = 'viewed'
    loading.value = false
    error.value = null
    _hydratingThreadIds.clear()
    _rehydrateWantedThreadIds.clear()
  }

  function _testSeedThread(raw) {
    _upsertThread(raw)
  }

  return {
    threadsById,
    messagesByThreadId,
    participantsByThreadId,
    unreadByThreadId,
    selectedThreadId,
    filters,
    productScope,
    loading,
    error,

    threadList,
    projectThreadList,
    townSquareThreadList,
    projectUnreadTotal,
    townSquareUnreadTotal,
    messagesFor,
    participantsFor,
    selectedThread,
    unreadFor,
    totalUnread,
    batonThreadIds,
    yourTurnCount,
    hasUserAttention,

    setProductScope,
    loadThreads,
    loadThread,
    loadParticipants,
    createThread,
    renameThread,
    retagThread,
    postMessage,
    passBaton,
    deleteThread,
    searchThreads,
    selectThread,
    markThreadRead,
    markThreadsRead,

    handleThreadMessage,
    handleThreadUpdate,
    hydrateThreadMessages,

    $reset,

    _testSeedThread,
  }
})
