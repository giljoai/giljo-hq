/**
 * useBannerPopoutLifecycle.js — FE-9553, completed by FE-9586
 *
 * Keeps the live browser popouts in step with the banners they are delivering.
 *
 * Ruling 4 calls a popout a delivery medium for a banner, not a class of its
 * own, and clause (c) makes that concrete: a popout follows banner state
 * including its death. So when a banner clears, its popout goes with it --
 * otherwise an OS notification outlives the thing it announced and the operator
 * answers a baton that was handed on ten minutes ago.
 *
 * WHY A RECONCILE AND NOT AN EVENT: ruling 3 says the banner follows STATE, not
 * memory -- acting in the Hub clears it. There is no "the baton left you" event
 * to subscribe to; the baton simply stops pointing at you in commHubStore. So
 * this watches exactly the state the banners themselves watch and closes
 * whatever no longer has a banner behind it. Anything event-driven would drift
 * the first time state changed by a path nobody emitted an event for -- a page
 * load with the baton already gone, for instance.
 *
 * ALL THREE REASONS ARE RECONCILED NOW (FE-9586). FE-9553 could only do the
 * baton: a mention raised no banner row at all, and an APPROVAL_FOCUS popout is
 * raised by a thread POST while the raised-hand banner is a `user_approvals`
 * record with no thread reference — two different objects sharing a word, so
 * matching one against the other would have closed every approval popout on the
 * first pass. Both now have real state: useThreadPostAttention projects the
 * server's unread mentions and pending DIRECTED action-requests, thread-keyed,
 * which is exactly the key the popout tag carries.
 *
 * A BROADCAST action-request is deliberately absent from that state. BE-9197
 * rules that such a post is "whoever picks it up" and obligates nobody in
 * particular; the client used to raise an actionable popout for one anyway,
 * which quietly contradicted the invariant. It keeps its durable bell row and
 * raises no popout, so there is nothing here to reconcile.
 *
 * NOTHING IS RECONCILED UNTIL THE STATE IS LOADED. `reconcilePopouts` closes
 * every tag absent from the live set, so an unhydrated source closes
 * everything — on a cold page load, silently, and only on a real OS where
 * popouts exist. `loaded` is the guard, and it is why useThreadPostAttention
 * starts at null rather than [].
 *
 * Edition Scope: Both
 */
import { computed, watch } from 'vue'

import { popoutTag } from '@/utils/popoutTag'
import { reconcilePopouts } from '@/utils/popoutRegistry'
import { BATON_FOCUS, MENTION_FOCUS, APPROVAL_FOCUS } from '@/components/hub/hubThreadRoute'

import { useYourTurnThreads } from './useYourTurnThreads'
import { useThreadPostAttention } from './useThreadPostAttention'

export function useBannerPopoutLifecycle() {
  const { yourTurnThreads } = useYourTurnThreads()
  const { mentions, directedAsks, loaded, ensureLoaded } = useThreadPostAttention()

  // The cold-load half: a mention or a directive already waiting when the page
  // loads is exactly what no live event will announce.
  ensureLoaded()

  /**
   * Every tag whose banner is still up.
   *
   * Derived through the shared popoutTag() rather than rebuilt by hand: the
   * closer and the opener must agree exactly, and a second spelling of the tag
   * would fail as a popout that can never be dismissed.
   */
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

  // immediate: a page load where the state is already gone is exactly the case
  // no live event will ever announce, and it is the common one after a restart.
  // The loaded gate makes that safe rather than destructive.
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
