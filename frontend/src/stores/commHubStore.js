/**
 * commHubStore.js — FE-6054e Agent Message Hub
 *
 * Pinia store for thread-based agent communications.
 * Mirrors the proven Map-based, immutable-upsert pattern from projectMessagesStore.js.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import { immutableMapSet, immutableMapDelete, immutableObjectPatch } from './immutableHelpers'
import api from '@/services/api'
import { useThreadPostAttention } from '@/composables/useThreadPostAttention'
import { useUserStore } from '@/stores/user'
import { useProductStore } from '@/stores/products'

// ---------------------------------------------------------------------------
// Normalization helpers
// ---------------------------------------------------------------------------

function normalizeMessage(raw) {
  if (!raw) return null
  const id = raw.message_id || raw.id
  if (!id) return null
  return {
    message_id: id,
    thread_id: raw.thread_id || null,
    from_agent_id: raw.from_agent_id || null,
    from_display_name: raw.from_display_name || raw.from_agent_id || 'unknown',
    // BE-9289a: 'agent' | 'user', resolved SERVER-SIDE at post time — the ONLY signal
    // for which side of the timeline a message belongs on. Carried by both the history
    // read and the live WS event. Defaults to 'agent' to match the column's own
    // default, so a payload from an older server never renders as the human user.
    from_kind: raw.from_kind || 'agent',
    content: raw.content || '',
    message_type: raw.message_type || 'broadcast',
    priority: raw.priority || 'normal',
    status: raw.status || null,
    requires_action: raw.requires_action || false,
    created_at: raw.created_at || null,
    // FE-9012c (D3/D4): per-message recipient acted-on state. Present only on a
    // history read with include_recipient_state=true; null (not []) when absent, so a
    // reader can tell "no junction data loaded" (e.g. a live WS message) from "no
    // recipients". FE-9289c: the Hub no longer opts in — the filter row that rendered
    // these is deleted — so today these are always null here. The normalizer keeps
    // carrying them because the REST parameter still exists and a caller that DOES
    // opt in must get them shaped correctly rather than silently dropped by an
    // allowlist. That allowlist-drops-a-new-field defect already cost this chain once.
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
    // FE-9530: the plural view -- project_id plus any additional
    // comm_thread_project_tags rows, deduplicated server-side. Defaults to []
    // (never null) so a card can always safely read .length / .map.
    project_ids: Array.isArray(raw.project_ids) ? raw.project_ids : raw.project_id ? [raw.project_id] : [],
    created_at: raw.created_at || null,
    // Derived: use updated_at if provided, else created_at, for activity sort
    last_activity_at: raw.updated_at || raw.last_activity_at || raw.created_at || null,
    // FE-9289c: the Quiet Cards enriched-list payload (BE-9289b). Present ONLY on the
    // list read, so each key is carried ONLY when raw actually has it — a partial
    // thread_update WS event (status/baton/subject) must not null a card's participants
    // or last_message. _upsertThread merges, so an omitted key preserves the prior value
    // (the same guard the b WS-subject fix taught).
    ...('title' in raw ? { title: raw.title || null } : {}),
    ...('project_name' in raw ? { project_name: raw.project_name || null } : {}),
    ...('participants' in raw ? { participants: Array.isArray(raw.participants) ? raw.participants : [] } : {}),
    ...('last_message' in raw ? { last_message: raw.last_message || null } : {}),
    ...('unread' in raw ? { unread: !!raw.unread } : {}),
  }
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

/**
 * FE-9586: re-read the thread-post projection after this viewer's read watermark
 * moves. Resolved lazily inside the action rather than at module scope, so the
 * store does not construct a composable while Pinia is still being set up.
 */
function refreshThreadPostAttention() {
  return useThreadPostAttention().refresh()
}

export const useCommHubStore = defineStore('commHub', () => {
  // ----- state -----
  const threadsById = ref(new Map())
  const messagesByThreadId = ref(new Map())
  const participantsByThreadId = ref(new Map())
  const selectedThreadId = ref(null)
  /** Map<thread_id, number> — unread message count per thread */
  const unreadByThreadId = ref(new Map())
  const filters = ref({
    status: null,
    owner: null,
    product_id: null,
    project_id: null,
  })
  /**
   * FE-9530: FE-9528's viewed-product scoping becomes the DEFAULT filter, not a
   * hard scope -- one Hub space, every thread reachable, with the viewed product
   * pre-selected so the everyday view is byte-identical to before this project.
   *
   * - 'viewed' (default): unchanged FE-9528 behaviour -- scoped to the viewed
   *   product tab; product-less threads excluded (reachable via searchThreads,
   *   same as before).
   * - 'all': every thread the tenant owns, regardless of product, INCLUDING
   *   product-less ones -- the explicit widen.
   * - 'unassigned': only threads with no product tag -- the explicit way to see
   *   what "no migration" left untagged, so they can be
   *   retagged via renameThread's sibling, retagThread.
   */
  const productScope = ref('viewed')
  const loading = ref(false)
  const error = ref(null)
  // BE-9414: thread_ids with a message-hydration read in flight, and thread_ids
  // that asked for one WHILE a read was in flight (so the coalesced follow-up pass
  // still serves them). Deliberately plain Sets, not refs — nothing renders them.
  const _hydratingThreadIds = new Set()
  const _rehydrateWantedThreadIds = new Set()

  // ----- getters -----

  /**
   * Sorted thread array: newest last_activity_at first.
   *
   * FE-9528: threadsById is an upsert cache fed by WS across every product
   * (FE-9502d's background-tab activity keeps arriving here even while the
   * operator views a different one), never wholesale-replaced by loadThreads
   * the way projects.js/tasks.js replace their list. So scoping the FETCH is
   * not enough — an already-cached other-product thread would stay visible
   * after switching tabs. Filtered here instead, by each thread's own
   * product_id against the viewed tab.
   *
   * FE-9530: that scoping is now the DEFAULT filter (productScope === 'viewed',
   * the initial value), not the only option — one Hub space, every thread
   * reachable via 'all', and 'unassigned' as the explicit way to find what
   * ruling 2's "no migration" left untagged. The FE-9528 cache-leak fix this
   * getter exists for applies in EVERY scope: 'all' still reads straight off
   * threadsById (no re-fetch needed, the cache already holds everything a
   * scoped fetch plus WS background activity accumulated), so widening never
   * reopens the leak the getter was built to close.
   */
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

  /** FE-9530: switch the Hub's product filter ('viewed' | 'all' | 'unassigned'). */
  function setProductScope(scope) {
    if (!['viewed', 'all', 'unassigned'].includes(scope)) return
    productScope.value = scope
  }

  // ----- FE-9012c (D2): two-tab split of the SAME thread list -----
  // "Project comms" = threads bound to a project; "Town square" = standalone.
  // Both derive from threadList (already newest-first) so sorting stays shared.

  /** Threads with a project_id (project-bound). */
  const projectThreadList = computed(() => threadList.value.filter((t) => t.project_id != null))

  /** Standalone threads (no project_id). */
  const townSquareThreadList = computed(() => threadList.value.filter((t) => t.project_id == null))

  /** Per-tab unread totals: sum the (a) cursor-derived per-thread unread counts. */
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

  // ----- unread + baton getters -----

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

  /** thread_ids where next_action_owner === currentUser.id */
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

  // ----- internal upsert helpers -----

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

  // ----- actions -----

  async function loadThreads(filterOverride) {
    loading.value = true
    error.value = null
    try {
      const params = { ...(filterOverride ?? filters.value) }
      // FE-9528: scope to the viewed product tab, mirroring projects.js/tasks.js.
      // The backend filters on strict equality (comm_thread_repository.list_threads),
      // so this EXCLUDES product-less threads once a tab is viewed — they are legal
      // (BE-9523b) and stay reachable via searchThreads, which the backend leaves
      // unscoped by construction (comm_threads.search_threads takes no product_id
      // at all — the REST handler, not the retired MCP tool of that name).
      //
      // FE-9530: only the DEFAULT scope ('viewed') auto-injects it. 'all' and
      // 'unassigned' fetch unscoped (matching the no-viewed-product fallback this
      // already had) — the getter above does the narrowing for 'unassigned' from
      // whatever the unscoped fetch plus the WS-fed cache already hold.
      if (params.product_id == null && productScope.value === 'viewed') {
        const productStore = useProductStore()
        if (productStore.currentProductId) params.product_id = productStore.currentProductId
      }
      // Strip null/undefined params
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
      // FE-9289c: the opt-in is dropped. The waiting/read/sent filter row was the only
      // thing that rendered the recipient junctions, and it is gone (DoD 7), so asking
      // for them fetched a payload nothing displays. The service parameter and the REST
      // query param stay — `include_recipient_state` is a clean opt-in read a future
      // caller may want; this is only the Hub declining to opt in.
      const res = await api.threads.history(id)
      const thread = res.data?.thread
      const messages = res.data?.messages || []
      if (thread) _upsertThread(thread)
      // Replace the message list for this thread with the full history
      const normalized = messages
        .map((m) => normalizeMessage(m))
        .filter(Boolean)
        .reduce((acc, m) => {
          if (!acc.find((x) => x.message_id === m.message_id)) acc.push(m)
          return acc
        }, [])
      messagesByThreadId.value = immutableMapSet(messagesByThreadId.value, id, normalized)
      // Viewing a thread clears its unread count
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

  /**
   * TSK-9300 — a 200 does not mean it worked.
   *
   * BE-9292a gave two thread routes (post, baton) a structured DECLINE returned at
   * HTTP 200: `{ success: false, error: <CODE>, hint, ... }`. That is deliberate — a
   * domain rejection is not an error (the BE-6081 carve-out) — so axios does not throw
   * and every `await` below looked like it had succeeded.
   *
   * These calls predate that shape: on these routes a 200 always DID mean success, so
   * checking was pointless when they were written. It is not any more. A refusal now
   * raises, carrying the server's own `hint` as the message so the caller shows the
   * operator what to do instead of a generic failure — the same contract renameThread
   * already follows. Callers must NOT discard the user's input on a throw.
   */
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
    // BE-9560: patch the baton locally from the response, same as passBaton below --
    // a reply that hands off or clears the turn (operator ruling 2026-09-02, "answering
    // means answering") must drop the your-turn banner in THIS tab immediately, not
    // wait on the best-effort WS baton broadcast (which covers every OTHER open tab).
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
    // TSK-9297: patch on SUCCESS, never on the mere presence of a thread_id — a refusal
    // carries one too. The server currently reports the UNCHANGED owner in its refusal,
    // so a naive patch happens to land on the truth; that is the server being careful,
    // not this store being correct, and it is not a property to depend on.
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

  /**
   * FE-9289c: rename a thread (BE-9289b PATCH), then patch the local subject on success
   * so the card and header reflect it immediately. Throws on rejection (e.g. a project
   * thread) so the caller can surface the reason as a toast — the store does not swallow
   * it. Also carries the returned title, since a rename can change the derived card title.
   */
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

  /**
   * FE-9530 — retag a thread's product and/or project tags via the same PATCH
   * `renameThread` uses (CommThreadService.update_thread, dual-door with the
   * MCP update_thread tool). This is the ONLY way an old, pre-existing thread
   * ever gets a product: operator ruling 2 forbids a bulk migration, so
   * retagging on touch is the mechanism, not a stopgap.
   *
   * `productId` — pass a UUID to set it, `null` to leave it untouched, or the
   * string `''` to explicitly clear it back to product-less (mirrors the
   * service's `clear_product` flag). `projectIds` — pass an array to
   * full-replace the thread's project tags (`[]` clears all), or omit/`null`
   * to leave them untouched.
   */
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

  /**
   * Soft-delete a thread, then drop it from local state (thread, its messages,
   * participants, unread count) and clear the selection if it was open.
   */
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

  /** Mark a thread's unread count as zero */
  function markThreadRead(threadId) {
    if (!threadId) return
    if ((unreadByThreadId.value.get(threadId) || 0) === 0) return
    unreadByThreadId.value = immutableMapSet(unreadByThreadId.value, threadId, 0)
  }

  /**
   * FE-9589: advance the read watermark on SEVERAL threads at once.
   *
   * The thread-post banner's multi-entry CTA had no way to clear itself: a
   * mention stops being reported only once the viewer's watermark passes the
   * naming post, and the only writer was selectThread() -- which needs a
   * thread to select. With more than one thread named, the CTA landed on the
   * Hub list, selected nothing, wrote no watermark, and the row stayed up
   * forever while agents kept posting.
   *
   * Writes local counters first so the strip settles immediately, then the
   * server writes, then ONE attention re-read for the whole batch rather than
   * one per thread. allSettled, not all: a thread that fails its write must
   * not abandon the rest, and the next open retries it.
   */
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
    // FE-9586: tell the SERVER too. markThreadRead above only zeroes a local
    // counter, so before this the operator had no read watermark at all and the
    // card's unread flag stayed true forever once anything was posted.
    //
    // Fire-and-forget by ruling: a failed watermark write must never delay or break
    // the thread view, and the next open retries it. Only a genuine open reaches
    // here — not list hover, not background prefetch.
    if (id) {
      api.threads
        .markRead(id)
        // FE-9586: the watermark just moved, and no WS event announces it -- it is
        // this viewer's own state, not the thread's. Without this re-read the
        // thread-post banner and its popout would sit there until some unrelated
        // message happened to arrive.
        .then(() => refreshThreadPostAttention())
        .catch(() => {})
    }
  }

  // ----- WebSocket handlers -----

  /**
   * handleThreadMessage — new message arrives on a thread.
   * Store-first: upsert into messagesByThreadId; deduplicate by message_id.
   * Increments unread count for threads that are not currently open.
   */
  async function handleThreadMessage(payload) {
    const threadId = payload?.thread_id
    if (!threadId) return
    _upsertMessage(threadId, payload)
    // Bump thread last_activity_at so sorting stays live
    const existing = threadsById.value.get(threadId)
    if (existing && payload.created_at) {
      threadsById.value = immutableMapSet(
        threadsById.value,
        threadId,
        immutableObjectPatch(existing, { last_activity_at: payload.created_at }),
      )
    }
    // Increment unread only for threads that are not currently open
    if (threadId !== selectedThreadId.value) {
      const prev = unreadByThreadId.value.get(threadId) || 0
      unreadByThreadId.value = immutableMapSet(unreadByThreadId.value, threadId, prev + 1)
    }

    // BE-9414: a long post travels as an excerpt (the cross-worker broker rides
    // pg_notify, capped at 7999 bytes), so the body has to be fetched.
    //
    // For EVERY thread, not only the one on screen. Scoping this to the open
    // thread looked like a saving and was a defect: useHubNotifications tests
    // `content` for the operator's display name, on every thread, so a mention
    // past the cut-off would silently stop raising the bell — a missed "you were
    // named" is worse than the extra read.
    if (payload.content_truncated) {
      await hydrateThreadMessages(threadId)
    }
  }

  /**
   * Re-read a thread's messages and merge them, WITHOUT the side effects of
   * loadThread (BE-9414).
   *
   * loadThread owns `loading` and writes `error`, which is right for an operator
   * opening a thread and wrong for a background top-up nobody asked for: it would
   * flicker the timeline into its loading state on every long post, and turn a
   * failed top-up into a Hub-wide error banner over a message the operator can
   * already partly read. Merging through _upsertMessage instead also patches the
   * in-flight excerpt into the full body in place, rather than swapping the whole
   * list out from under the renderer.
   *
   * Concurrent requests COALESCE rather than drop. A burst of long posts must not
   * become a burst of identical GETs — but it must not lose the tail either: a read
   * already in flight may have queried before the newer message was committed, so
   * merely skipping would leave that one stuck on its excerpt. One follow-up pass
   * serves everything that arrived during the first, so the last request is always
   * answered by a read that started after it. N posts cost at most 2 reads.
   */
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

  /**
   * handleThreadUpdate — thread meta changes (status, baton, new thread).
   */
  function handleThreadUpdate(payload) {
    const threadId = payload?.thread_id
    if (!threadId) return

    if (payload.update_type === 'deleted') {
      // Another client soft-deleted this thread — drop it everywhere locally.
      _removeThreadLocal(threadId)
      return
    }

    if (payload.update_type === 'created' && !threadsById.value.has(threadId)) {
      // Unknown thread created — trigger a refresh
      loadThreads(filters.value)
      return
    }

    if (payload.update_type === 'restored' && !threadsById.value.has(threadId)) {
      // A soft-deleted thread was recovered (FE-6138) — re-surface it in the list.
      loadThreads(filters.value)
      return
    }

    const existing = threadsById.value.get(threadId)
    if (!existing) return

    const patch = {}
    if (payload.status != null) patch.status = payload.status
    if (payload.next_action_owner != null) patch.next_action_owner = payload.next_action_owner
    if (payload.chat_id != null) patch.chat_id = payload.chat_id
    // BE-9289b: a rename arrives on the same event. Null-guarded like the rest, so an
    // event that carries no subject leaves the existing one alone.
    if (payload.subject != null) patch.subject = payload.subject

    if (Object.keys(patch).length === 0) return
    const updated = immutableObjectPatch(existing, patch)
    if (JSON.stringify(existing) === JSON.stringify(updated)) return
    threadsById.value = immutableMapSet(threadsById.value, threadId, updated)
  }

  // ----- lifecycle -----

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

  /**
   * Test-only helper: directly seed a thread into the store without an API call.
   * Only exposed in the return map; tree-shaken in production by the store.
   */
  function _testSeedThread(raw) {
    _upsertThread(raw)
  }

  return {
    // state
    threadsById,
    messagesByThreadId,
    participantsByThreadId,
    unreadByThreadId,
    selectedThreadId,
    filters,
    productScope,
    loading,
    error,

    // getters
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

    // actions
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

    // ws handlers
    handleThreadMessage,
    handleThreadUpdate,
    hydrateThreadMessages,

    // lifecycle
    $reset,

    // test helpers (used in commHubStore.spec.js — tree-shaken otherwise)
    _testSeedThread,
  }
})
