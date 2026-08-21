/**
 * useMarkHandled.js — FE-9439
 *
 * Clearing "waiting on you", once, for the two surfaces that offer it: the persistent
 * toggle beside the thread search bar and the pulsing one in the composer.
 *
 * WHY A COMPOSABLE AND NOT A SECOND BUTTON
 *
 * FE-9365g put the release valve in the composer alone, as a small text button at the
 * bottom of the thread. The operator's report was that it may as well not exist — "it
 * exists at the bottom by the chat bar but is not very distinct". The answer is a second
 * PLACE to reach the action, not a second IMPLEMENTATION of it: two copies of a handler
 * that clears a baton and rewrites a route is the next bug report, because one of them
 * gets fixed and the other does not. The control's looks live in MarkHandledToggle.vue,
 * its behaviour lives here, and the two callers own neither.
 *
 * WHY THIS TOUCHES THE ROUTE AT ALL (FE-9439 item 3)
 *
 * Because the flag it clears is rendered FROM the route, and that is the whole defect.
 * The Hub pins "Waiting on you" above a post when the URL says
 * `?thread=<id>&focus=baton&message=<id>` — FE-9418's exact pinning, unified through
 * hubThreadRoute.js by FE-9436. FE-9365g cleared the baton server-side and stopped
 * there, so the view was still being told, by its own route, to pin a focus the server
 * had just dropped. The call succeeded and the flag stayed on screen.
 *
 * So the fix belongs at the layer that lies: drop `focus` and `message` from the query.
 * Not a second dismissal path — FE-9436 deliberately unified this to one pipeline, and
 * a `dismissed` flag beside the query would be a second source of truth about the same
 * question. Making the existing pipeline honour the cleared baton is the smaller change
 * and the honest one.
 *
 * Edition scope: Both
 */
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCommHubStore } from '@/stores/commHubStore'
import { useUserStore } from '@/stores/user'
import { useToast } from '@/composables/useToast'

export function useMarkHandled() {
  const commHub = useCommHubStore()
  const userStore = useUserStore()
  const route = useRoute()
  const router = useRouter()
  const { showToast } = useToast()

  /** True when the selected thread's baton points at the current user. */
  const isYourTurn = computed(() => {
    const thread = commHub.selectedThread
    return thread?.next_action_owner != null && thread.next_action_owner === userStore.currentUser?.id
  })

  const clearing = ref(false)

  /**
   * Drop the focus params, keeping everything else the route carries.
   *
   * Rebuilt as an object and handed to the router — never string-composed (ADR-001/003).
   * `thread` and `tab` survive untouched, which is what keeps the operator standing in
   * the conversation they were reading: HubView watches `route.query.thread`, so
   * preserving it is also what stops this from re-running the deep-link fetch and
   * throwing the scroll position away.
   *
   * `replace`, not `push`. A cleared flag is not a place in history worth a Back button —
   * and if it were pushed, Back would restore the stale `focus=baton` and put the pin
   * straight back on screen.
   */
  function clearFocusFromRoute() {
    const { focus, message, ...rest } = route.query
    // Nothing to do if the operator did not arrive from a notification — the ordinary
    // case. Skipping the call keeps a no-op navigation out of the router entirely.
    if (focus === undefined && message === undefined) return
    router.replace({ path: route.path, query: rest })
  }

  /**
   * Clear the turn: no post, thread stays open, and the pin goes with it.
   *
   * The route is rewritten only AFTER the server confirms. On a refusal the baton still
   * points at the operator, so removing the flag would hide live state behind a click
   * that looked like it worked — the failure mode is worse than the one being fixed.
   */
  async function markHandled() {
    const threadId = commHub.selectedThreadId
    if (!threadId || clearing.value) return
    clearing.value = true
    try {
      // 'none' is the reserved no-owner target: next_action_owner clears, the gold
      // frame and hand go out, and no agent is told to act.
      await commHub.passBaton(threadId, 'none')
      clearFocusFromRoute()
      showToast({ type: 'success', message: 'Handled — the turn is cleared.' })
    } catch (err) {
      const msg = err?.response?.data?.detail || err?.message || 'Could not clear the turn.'
      showToast({ type: 'error', message: msg })
    } finally {
      clearing.value = false
    }
  }

  return { isYourTurn, clearing, markHandled }
}
