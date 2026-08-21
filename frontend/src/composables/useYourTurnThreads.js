/**
 * useYourTurnThreads.js — FE-9368 (E)
 *
 * The threads where an agent has handed the turn to the operator, available from ANY
 * page. The Message Hub already answers this question, but only while you are standing
 * in it; the operator is normally somewhere else when the baton lands.
 *
 * Two rules are carried over verbatim from the Hub, because a second definition of
 * "your turn" that disagrees with the first is worse than no banner at all:
 *
 *   1. IT COMES FROM THE BATON AND NOTHING ELSE. next_action_owner === you. However
 *      urgently a post is worded, prose never lights this up (ThreadCard/HubView).
 *   2. A TERMINAL THREAD IS NEVER YOUR TURN. resolved/closed threads keep whatever
 *      baton they stopped on; "done" and "waiting on you" cannot both be true
 *      (FE-9365i, caught live on the cards).
 *
 * Liveness: the WS event router is app-wide and feeds commHubStore.handleThreadUpdate,
 * so a baton handed over while the operator is on any page patches the store and this
 * list re-computes. ensureThreadsLoaded() covers the other half: a baton already
 * pointing at them when the page loads, which no live event will ever announce.
 */
import { computed } from 'vue'
import { useCommHubStore } from '@/stores/commHubStore'
import { useUserStore } from '@/stores/user'

const TERMINAL = new Set(['resolved', 'closed'])

export function useYourTurnThreads() {
  const commHub = useCommHubStore()
  const userStore = useUserStore()

  /** Non-terminal threads whose baton points at the current user, newest first. */
  const yourTurnThreads = computed(() => {
    const me = userStore.currentUser?.id
    if (!me) return []
    return commHub.threadList.filter(
      (t) =>
        t.next_action_owner === me && !TERMINAL.has(String(t.status || '').toLowerCase()),
    )
  })

  // One list read per mount. loadThreads() swallows its own transport errors and
  // leaves the store empty, so a failure here costs the banner, never the page.
  let requested = false
  async function ensureThreadsLoaded() {
    if (requested) return
    if (!userStore.currentUser?.id) return
    requested = true
    await commHub.loadThreads()
  }

  return { yourTurnThreads, ensureThreadsLoaded }
}
