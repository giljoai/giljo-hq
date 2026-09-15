import { computed, watch } from 'vue'

import { useBannerDismissStore } from '@/stores/bannerDismissStore'

export const approvalDismissKey = (approval) => (approval?.id ? `approval:${approval.id}` : null)

export const mentionDismissKey = (mention) =>
  mention?.thread_id ? `mention:${mention.thread_id}:${mention.message_ids?.[0] ?? ''}` : null

export const askDismissKey = (ask) => (ask?.thread_id ? `ask:${ask.thread_id}` : null)

export const yourTurnDismissKey = (thread) =>
  thread?.thread_id ? `your-turn:${thread.thread_id}:${thread.last_message?.id ?? ''}` : null

export function useBannerDismiss(sources) {
  const store = useBannerDismissStore()

  const keep = (list, keyOf) => (list.value || []).filter((row) => !store.isDismissed(keyOf(row)))

  const visibleApprovals = computed(() => keep(sources.approvals, approvalDismissKey))
  const visibleMentions = computed(() => keep(sources.mentions, mentionDismissKey))
  const visibleDirectedAsks = computed(() => keep(sources.directedAsks, askDismissKey))
  const visibleYourTurnThreads = computed(() => keep(sources.yourTurnThreads, yourTurnDismissKey))

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
