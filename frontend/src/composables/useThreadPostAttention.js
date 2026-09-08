/**
 * useThreadPostAttention.js — FE-9586
 *
 * The thread-post signals that are asking for the operator right now: unread
 * MENTIONS and pending DIRECTED action-requests.
 *
 * WHY THIS EXISTS. FE-9553 settled that a popout is a delivery medium for a
 * banner and follows banner state including its death. That join was
 * built for the baton, which has a banner fed by state. A mention had no banner
 * at all and a directed ask had none either, so both shipped event-shaped with a
 * ten-minute TTL — a guarantee against permanence rather than a projection. This
 * is the state they were missing.
 *
 * SERVER-OWNED, NOT DERIVED HERE. "Was I mentioned" used to be a display-name
 * substring match in useHubNotifications, which is now deleted: the server owns
 * that definition (GET /api/v1/threads/attention). Two definitions that can
 * disagree is the failure this project removes — and the client's could not even
 * see the whole post, since a long body reaches it as a bounded excerpt, so a
 * mention written past the cut-off was invisible to the reader it named.
 *
 * NULL MEANS NOT LOADED, and that is the load-bearing part of this module. The
 * FE-9553 reconcile survived only because useYourTurnThreads does its own
 * ensureThreadsLoaded(), so an empty list genuinely meant empty. If these
 * arrived as plain arrays defaulting to [], a cold page load would be
 * indistinguishable from "nothing is waiting" and the reconcile would close
 * every popout on mount — silently, and only on a real OS where popouts exist.
 * So the refs start as null, `loaded` is false until the first successful read,
 * and every consumer must check it before concluding anything is absent.
 *
 * MODULE-SCOPED STATE on purpose: the banner, the popout lifecycle and the
 * notification path all have to read ONE answer. Per-caller refs would give the
 * reconcile its own permanently-unloaded copy.
 *
 * Edition Scope: Both
 */
import { computed, ref } from 'vue'

import api from '@/services/api'

/** null until the first successful read — see the docblock. */
const mentions = ref(null)
const directedAsks = ref(null)

let inFlight = null
let requested = false
let listening = false

/**
 * Refresh from the server, collapsing concurrent callers onto one request.
 *
 * A burst of thread_message events is the normal case (an orchestrator fanning
 * out directives), and one read answers all of them. Transport errors leave the
 * previous state alone rather than clearing it: a failed poll is not evidence
 * that nothing is waiting, and treating it as such is how a banner disappears
 * while the thing it announced is still owed.
 */
async function refresh() {
  if (inFlight) return inFlight
  inFlight = (async () => {
    try {
      const res = await api.threads.attention()
      mentions.value = Array.isArray(res?.data?.mentions) ? res.data.mentions : []
      directedAsks.value = Array.isArray(res?.data?.directed_action) ? res.data.directed_action : []
    } catch {
      // Keep whatever we last knew. Never fall back to [].
    } finally {
      inFlight = null
    }
  })()
  return inFlight
}

/** One read per page load, however many consumers ask for it. */
async function ensureLoaded() {
  if (requested) return
  requested = true
  await refresh()
}

/**
 * Re-read when the Hub says something happened.
 *
 * The events are a HINT to re-ask, not the answer: the verdict is the server's.
 * That is what makes this a projection rather than a second event pipeline, and
 * it is why a page load with a mention already waiting — which no live event
 * will ever announce — is covered by ensureLoaded() instead.
 *
 * Registered once at module scope and never torn down, because the state it
 * feeds is module-scoped too and outlives any single component.
 */
function listen() {
  if (listening || typeof window === 'undefined') return
  listening = true
  window.addEventListener('hub:thread_message', () => refresh())
  window.addEventListener('hub:thread_update', () => refresh())
}

export function useThreadPostAttention() {
  listen()

  return {
    /** [{thread_id, chat_id, message_ids}] — null until loaded. */
    mentions,
    /** [{thread_id, chat_id}] — null until loaded. */
    directedAsks,
    /** False until the first successful read. Check it before concluding absence. */
    loaded: computed(() => mentions.value !== null),
    /** Total rows asking for the operator; 0 while unloaded. */
    attentionCount: computed(
      () => (mentions.value?.length || 0) + (directedAsks.value?.length || 0),
    ),
    ensureLoaded,
    refresh,
  }
}

/** Test-only: module-scoped state would otherwise leak between specs. */
export function __resetThreadPostAttention() {
  mentions.value = null
  directedAsks.value = null
  inFlight = null
  requested = false
}
