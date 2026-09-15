import { computed, watch } from 'vue'

import { popoutTag } from '@/utils/popoutTag'
import { reconcilePopouts } from '@/utils/popoutRegistry'
import { BATON_FOCUS, MENTION_FOCUS, APPROVAL_FOCUS } from '@/components/hub/hubThreadRoute'

import { useYourTurnThreads } from './useYourTurnThreads'
import { useThreadPostAttention } from './useThreadPostAttention'

export function useBannerPopoutLifecycle() {
  const { yourTurnThreads } = useYourTurnThreads()
  const { mentions, directedAsks, loaded, ensureLoaded } = useThreadPostAttention()

  ensureLoaded()

  const liveTags = computed(() => {
    const tags = new Set()

    for (const thread of yourTurnThreads.value || []) {
      const id = thread?.thread_id ?? thread?.id
      if (id) tags.add(popoutTag(BATON_FOCUS, id))
    }
    for (const mention of mentions.value || []) {
      if (mention?.thread_id) tags.add(popoutTag(MENTION_FOCUS, mention.thread_id))
    }
    for (const ask of directedAsks.value || []) {
      if (ask?.thread_id) tags.add(popoutTag(APPROVAL_FOCUS, ask.thread_id))
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
