import { computed, watch } from 'vue'

import { popoutTag } from '@/utils/popoutTag'
import { reconcilePopouts } from '@/utils/popoutRegistry'
import { BATON_FOCUS, MENTION_FOCUS, APPROVAL_FOCUS } from '@/components/hub/hubThreadRoute'
import { useUserStore } from '@/stores/user'

import { useYourTurnThreads } from './useYourTurnThreads'
import { useThreadPostAttention } from './useThreadPostAttention'
import { liveStoppedAgentKeys } from './useStoppedAgentSignals'

export function useBannerPopoutLifecycle() {
  const { yourTurnThreads } = useYourTurnThreads()
  const { mentions, directedAsks, loaded, ensureLoaded } = useThreadPostAttention()

  ensureLoaded()

  const liveTags = computed(() => {
    const tags = new Set()
    const userId = useUserStore().currentUser?.id

    for (const thread of yourTurnThreads.value || []) {
      const id = thread?.thread_id
      if (id) tags.add(popoutTag(BATON_FOCUS, id, userId))
    }
    for (const mention of mentions.value || []) {
      if (mention?.thread_id) tags.add(popoutTag(MENTION_FOCUS, mention.thread_id, userId))
    }
    for (const ask of directedAsks.value || []) {
      if (ask?.thread_id) tags.add(popoutTag(APPROVAL_FOCUS, ask.thread_id, userId))
    }
    for (const { reason, key } of liveStoppedAgentKeys()) {
      tags.add(popoutTag(reason, key, userId))
    }

    return tags
  })

  watch(
    [liveTags, loaded],
    ([tags, isLoaded]) => {
      if (!isLoaded) return
      reconcilePopouts(tags)
    },
    { immediate: true },
  )

  return { liveTags }
}
