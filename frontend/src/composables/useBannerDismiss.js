/**
 * useBannerDismiss.js — FE-9589
 *
 * The banner strip's side of dismissal: it turns each live-state row family
 * into a dismissal KEY, hides the rows whose key is dismissed, and reconciles
 * stale keys away. bannerDismissStore owns the persistence; this owns what a
 * key MEANS for each family, and it lives here rather than in
 * SystemStatusBanner.vue for Guardrail 1 (that file is at its size ceiling).
 *
 * Three families, three key shapes, one rule behind all of them: the key must
 * change when the obligation does, so dismissing today's raised hand never
 * silences tomorrow's.
 *
 *   approval    `approval:<approval_id>`            -- ids are per-approval, so a
 *                                                      new question is a new key.
 *   mention     `mention:<thread_id>:<newest post>` -- message_ids arrive
 *                                                      newest-first from the
 *                                                      attention projection, so a
 *                                                      further naming post
 *                                                      re-announces the thread.
 *   ask         `ask:<thread_id>`                   -- the projection reports a
 *                                                      directed ask per THREAD
 *                                                      with no post id, so this
 *                                                      key cannot change on its
 *                                                      own; reconcile carries it.
 *   your-turn   `your-turn:<thread_id>:<last post>` -- the post the baton came
 *                                                      with, as the Hub route
 *                                                      names it.
 *
 * RECONCILE IS GUARDED ON HYDRATION, not on emptiness. An unloaded read and
 * "nothing is waiting" are the same empty list, and reconciling against the
 * former would un-dismiss every row on each cold load -- the FE-9553 trap that
 * useThreadPostAttention's `loaded` flag exists to keep out of this code.
 *
 * Edition Scope: Both
 */
import { computed, watch } from 'vue'

import { useBannerDismissStore } from '@/stores/bannerDismissStore'

export const approvalDismissKey = (approval) => (approval?.id ? `approval:${approval.id}` : null)

export const mentionDismissKey = (mention) =>
  mention?.thread_id ? `mention:${mention.thread_id}:${mention.message_ids?.[0] ?? ''}` : null

export const askDismissKey = (ask) => (ask?.thread_id ? `ask:${ask.thread_id}` : null)

export const yourTurnDismissKey = (thread) =>
  thread?.thread_id ? `your-turn:${thread.thread_id}:${thread.last_message?.id ?? ''}` : null

/**
 * @param sources.approvals         Ref<Array>  pending approvals
 * @param sources.approvalsLoaded   Ref<bool>   the pending-approval read has landed
 * @param sources.mentions          Ref<Array>  attention projection mentions
 * @param sources.directedAsks      Ref<Array>  attention projection directed asks
 * @param sources.attentionLoaded   Ref<bool>   the attention projection has landed
 * @param sources.yourTurnThreads   Ref<Array>  threads whose baton points at the user
 * @param sources.threadsLoaded     Ref<bool>   the Hub thread list has landed
 */
export function useBannerDismiss(sources) {
  const store = useBannerDismissStore()

  const keep = (list, keyOf) => (list.value || []).filter((row) => !store.isDismissed(keyOf(row)))

  const visibleApprovals = computed(() => keep(sources.approvals, approvalDismissKey))
  const visibleMentions = computed(() => keep(sources.mentions, mentionDismissKey))
  const visibleDirectedAsks = computed(() => keep(sources.directedAsks, askDismissKey))
  const visibleYourTurnThreads = computed(() => keep(sources.yourTurnThreads, yourTurnDismissKey))

  // Dismissing a ROW dismisses every obligation it is currently announcing --
  // the row is one strip standing for the whole set its pills name, so silencing
  // it while leaving half the set live would just redraw it unchanged.
  function dismissApprovals() {
    store.dismiss(visibleApprovals.value.map(approvalDismissKey))
  }

  function dismissThreadPosts() {
    store.dismiss([
      ...visibleMentions.value.map(mentionDismissKey),
      ...visibleDirectedAsks.value.map(askDismissKey),
    ])
  }

  function dismissYourTurn() {
    store.dismiss(visibleYourTurnThreads.value.map(yourTurnDismissKey))
  }

  function reconcileFamily(prefix, loaded, list, keyOf) {
    if (!loaded.value) return
    store.reconcile(prefix, new Set((list.value || []).map(keyOf).filter(Boolean)))
  }

  watch(
    [sources.approvalsLoaded, sources.approvals],
    () => reconcileFamily('approval:', sources.approvalsLoaded, sources.approvals, approvalDismissKey),
    { immediate: true },
  )

  watch(
    [sources.attentionLoaded, sources.mentions],
    () => reconcileFamily('mention:', sources.attentionLoaded, sources.mentions, mentionDismissKey),
    { immediate: true },
  )

  watch(
    [sources.attentionLoaded, sources.directedAsks],
    () => reconcileFamily('ask:', sources.attentionLoaded, sources.directedAsks, askDismissKey),
    { immediate: true },
  )

  watch(
    [sources.threadsLoaded, sources.yourTurnThreads],
    () => reconcileFamily('your-turn:', sources.threadsLoaded, sources.yourTurnThreads, yourTurnDismissKey),
    { immediate: true },
  )

  return {
    visibleApprovals,
    visibleMentions,
    visibleDirectedAsks,
    visibleYourTurnThreads,
    dismissApprovals,
    dismissThreadPosts,
    dismissYourTurn,
  }
}
