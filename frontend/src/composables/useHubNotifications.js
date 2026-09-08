/**
 * useHubNotifications.js — FE-6054f
 *
 * Gated, no-spam alerting for the Agent Message Hub.
 *
 * Fires ONLY for user-invoked events:
 *   1. thread_update: next_action_owner === currentUser.id  (PRIMARY — baton handed to operator)
 *   2. thread_message: requires_action === true AND to_participant === currentUser.id —
 *      a DIRECTED action-request. FE-9546 established that a requires_action post aimed
 *      at another agent is that agent's business; FE-9586 finished the thought and
 *      dropped the BROADCAST case too (see below).
 *   3. MENTIONS no longer come from an event at all — they are projected from the
 *      server (see the mention section below).
 *
 * Own posts (from_agent_id === currentUser.id) are NEVER signalled.
 *
 * WHAT THE CLIENT MAY AND MAY NOT DECIDE (FE-9586). The line is identity versus
 * interpretation. `to_participant === userId` is an ID COMPARISON against the same
 * field the server keys on, delivered in the event — the client can do that exactly
 * right, so it stays here. "Does this post mention me" was an INTERPRETATION of the
 * post's text, and the client could not even see all of it: a long body reaches
 * the client as a bounded excerpt, so the client cannot reliably decide whether it
 * was named. That verdict is resolved server-side against the full body and the
 * client consumes it.
 *
 * A BROADCAST requires_action POST IS QUIET, NOT SILENT. It used to get the full
 * attention treatment, on the reading that an absent to_participant meant "all
 * recipients must act". BE-9197 rules the opposite and the server has always agreed —
 * its directed-action query excludes broadcasts because such a post is "whoever picks
 * it up" and obligates nobody in particular. So the client is aligned rather than the
 * invariant: no banner, no popout, no toast.
 *
 * FE-9586b: it DOES keep its durable bell row, and this is a regression fix rather
 * than a new rule. FE-9586 said in this very docblock that the post "keeps its
 * durable bell row" — and it did not, because the bell row is written AFTER the
 * signal gate, so returning null from the gate skipped the bell too and the post
 * vanished from every surface at once. Documented intent and shipped behaviour
 * disagreed; the operator noticed by losing track of asks his agents broadcast.
 * The gate now returns a QUIET signal for that case instead of nothing, which is
 * what ruling 1 means by the bell being the archive for a missed event.
 *
 * Routing by VISIBILITY (FE-9553, ruling 4(a)) — was routing by Hub presence:
 *   - app visible  → the banner alone. No popout, no toast.
 *   - app hidden   → browser Notification (if granted), carrying a stable tag.
 *   - either way   → the durable bell row. NOTE it is written after getSignal(), so
 *                    a signal the gate REJECTS gets no bell row either — which is the
 *                    FE-9586b bug. A post that should be recorded but not interrupt
 *                    must come back from the gate as `quiet`, never as null.
 *
 * FE-9553 also removed the toast that used to fire alongside the popout: these
 * signals are actionable and agent-initiated, so they belong to the banner and
 * the bell, not the toast (rulings 3 and 6). And the gate moved from
 * `isHubPresent` to `document.hidden`, because those are different questions
 * and the old one popped an OS notification at a window the operator was
 * already looking at whenever they were on any page except the Hub.
 *
 * Permission is requested LAZILY on first qualifying away event.
 * De-duplicates: same signal key does not fire twice until the key changes.
 */
import { onScopeDispose, getCurrentScope, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useCommHubStore } from '@/stores/commHubStore'
import { useNotificationStore } from '@/stores/notifications'
import {
  hubThreadRoute,
  BATON_FOCUS,
  MENTION_FOCUS,
  APPROVAL_FOCUS,
} from '@/components/hub/hubThreadRoute'
import { threadDisplayName } from '@/components/hub/threadDisplayName'
import { popoutTag } from '@/utils/popoutTag'
import { registerPopout } from '@/utils/popoutRegistry'
import { useSettingsStore } from '@/stores/settings'

import { useThreadPostAttention } from './useThreadPostAttention'

/**
 * FE-9439: the badge on a desktop (OS-level) notification.
 *
 * A padded square PNG rather than the app's SVGs, because this slot is not ours: the OS
 * renders it at a size and on a background we do not control, and it letterboxes a
 * non-square source. Solid navy for the same reason — see the note at the call site.
 */
const NOTIFICATION_ICON = '/icons/Giljo_Face_Avatar.png'

/**
 * FE-9436: what the announcer CALLS each reason.
 *
 * The hand-off's title is FE-9289c's, unchanged. The other two shared the generic
 * "Message Hub" because the event name — the only thing the caller had — cannot tell a
 * mention from an approval: both arrive as `thread_message`. The signal gate always
 * knew, and now says so, which is the whole of "one announcer, reason is the only
 * difference" at this layer.
 */
const ANNOUNCER_TITLES = {
  [BATON_FOCUS]: "It's your call",
  [MENTION_FOCUS]: 'You were mentioned',
  [APPROVAL_FOCUS]: 'Needs your approval',
}

/**
 * FE-9586b: what a QUIET signal is called in the bell.
 *
 * The bell list is the one place a broadcast ask and a directed ask sit side by side,
 * and "Needs your approval" on a post nobody in particular owes is the same false
 * claim FE-9586 removed from the banner. Only the bell renders this — a quiet signal
 * raises no popout, so there is no announcer title to keep in step.
 */
const QUIET_BELL_TITLES = {
  [APPROVAL_FOCUS]: 'Open ask from an agent',
}

/**
 * FE-9436: the durable bell row each reason drops.
 *
 * `type` is what notificationRouting's TYPE_ROUTE_MAP dispatches on. The hand-off's is
 * the bare legacy `handover` and its id stays thread-keyed: these rows live in the
 * browser's own storage, so renaming either would orphan every row a user is already
 * holding. The two new ones are namespaced like the server's types, which is the better
 * convention and costs nothing to adopt for rows that do not exist yet.
 *
 * `keyOnPost` is the substantive difference. A second hand-off in a thread is the SAME
 * standing obligation — answer it — so it collapses onto one row. A second mention is a
 * second thing somebody asked you, and collapsing those loses one of them.
 */
const BELL_ROWS = {
  [BATON_FOCUS]: { type: 'handover', prefix: 'handover', keyOnPost: false },
  [MENTION_FOCUS]: { type: 'hub.mention', prefix: 'mention', keyOnPost: true },
  [APPROVAL_FOCUS]: { type: 'hub.approval', prefix: 'approval', keyOnPost: true },
}

export function useHubNotifications() {
  const router = useRouter()
  const { mentions, ensureLoaded } = useThreadPostAttention()

  // A mention already waiting at page load is announced by nothing else.
  ensureLoaded()

  // FE-9289c: the handover deep-links to its thread. HubView reads ?thread=<id> on
  // mount and selects it, so this works from a COLD page (bell clicked while the app is
  // on Dashboard) — route first, HubView selects on arrival.
  //
  // FE-9418: a HAND-OFF routes through hubThreadRoute(), the same helper the app-wide
  // banner, the Hub's attention strip and both bell rows use, so one baton cannot land
  // in two places depending on which of the four notifications the operator clicked.
  //
  // FE-9436: so does everything else. FE-9418 deliberately left mentions and approvals
  // on a hand-built literal, because the helper could only stamp `focus=baton` and that
  // is what renders "Waiting on you" — a label nobody had handed over. The helper now
  // carries the REASON, so the objection is gone and the last hand-built Hub route on
  // this surface goes with it. One route writer, three reasons.
  function openThread(threadId, { reason = BATON_FOCUS, messageId = null } = {}) {
    if (!threadId) return
    try {
      window.focus()
    } catch {
      // noop — focus can throw in some embeddings
    }
    // A bare id, never the store's thread object — even though the store has one. Its
    // `last_message` is refreshed only by a thread-list read (`handleThreadMessage`
    // bumps last_activity_at and nothing else), so at hand-off time it names whatever
    // was newest when the list was last fetched, NOT the post that handed the baton
    // over. Passing it would pin the operator to a stale message; the tail fallback
    // resolves the real one from the loaded timeline instead.
    //
    // A mention or an approval needs no such fallback: its own event NAMES the post
    // (`thread_message` carries message_id, where the baton's `thread_update` does not),
    // so `messageId` is the live id and never the summary's.
    router.push(hubThreadRoute(threadId, { reason, messageId })).catch(() => {})
  }

  /**
   * What to CALL the thread in the words the operator reads.
   *
   * FE-9436: never its id. This one string reaches three surfaces at once — the toast,
   * the browser notification and the durable bell row — and its old last resort was
   * `thread <uuid>`, which fired precisely when the store had not hydrated the thread:
   * the cold-page, away-from-the-app case the browser notification exists for. So the
   * common case was the one that showed a UUID.
   *
   * The rule itself is shared with the banner and the Hub's own toast, because all three
   * describe the same threads to the same person — see `threadDisplayName`.
   */
  function threadLabel(threadId, payload) {
    return threadDisplayName(useCommHubStore().threadsById?.get?.(threadId), payload)
  }

  // BE-9414's messageContent() helper lived here and is GONE (FE-9586). It existed
  // to give the mention match the full body rather than the broker's excerpt, and
  // its own docblock conceded it fell back to the excerpt whenever the hydrating
  // read had failed — which is the case the mention match most needed it for. The
  // match moved server-side, where the content column is simply readable, so the
  // helper has no caller and the failure mode it half-mitigated is gone rather than
  // narrowed.

  // De-dupe: track the last-signalled key so identical back-to-back events don't spam
  const lastSignalledKey = new Set()

  // ── Notification permission (lazy, non-blocking) ──

  let permissionRequested = false

  function requestPermissionLazy() {
    if (typeof Notification === 'undefined') return
    if (Notification.permission !== 'default') return
    if (permissionRequested) return
    permissionRequested = true
    try {
      // Fire-and-forget — we don't block on the result; next event will check permission
      Notification.requestPermission().catch(() => {})
    } catch {
      // Older browsers may not return a promise; ignore
    }
  }

  function fireNotification(title, body, threadId, { reason, messageId } = {}) {
    if (typeof Notification === 'undefined') return

    // FE-9553 ruling 5: the operator's popout scope. This is the ONE place the
    // preference is read, because it is the one place a popout is raised --
    // gating at the call sites instead would need every future caller to
    // remember, which is the failure mode the whole project exists to remove.
    //
    // 'off' suppresses. 'actionable' admits decisions, batons and mentions,
    // which is every reason that reaches this function today. 'all' additionally
    // admits lifecycle, which nothing currently pops -- see the note in
    // useHubNotifications.popouts.fe9553.spec.js about why those two positions
    // are indistinguishable until a lifecycle popout exists.
    //
    // Permission is NOT requested when the operator has said off: asking a
    // browser for a capability we have been told not to use is the sort of
    // prompt that gets a site permanently blocked.
    if (useSettingsStore().popoutScope === 'off') return

    requestPermissionLazy()
    if (Notification.permission !== 'granted') return
    try {
      // FE-9439: the AVATAR, not the wordmark. `/Giljo_YW.svg` is the yellow GiljoAI
      // wordmark, which is what the Windows notification popup was showing — a strip of
      // text where every other surface in the app (composer, agent rows, setup wizard,
      // status banner) shows the face. The solid dark-navy PNG is deliberate: notification
      // chrome is a surface we do not control, and the transparent variant loses its light
      // grey eyes against a light-theme OS background.
      // FE-9553 ruling 4(c): a popout follows banner STATE, including its
      // death, so it needs a name the state can address it by. The tag is
      // derived from the signal and the thread rather than minted fresh: the
      // OS replaces a same-tag notification instead of stacking a second one,
      // and the same derivation lets the state that raised it close it again.
      // A random tag would dedupe nothing and could never be closed.
      const tag = popoutTag(reason, threadId)
      const n = new Notification(title, { body, icon: NOTIFICATION_ICON, tag })
      // FE-9289c: clicking the handover lands on its thread, not just the app.
      // FE-9436: and clicking a mention or an approval lands on its POST.
      n.onclick = () => openThread(threadId, { reason, messageId })

      // FE-9553 ruling 4(c): hand the popout to the registry so the state that
      // raised it can close it again.
      //
      // FE-9586: no state-backed flag any more, because all three reasons are.
      // The baton follows useYourTurnThreads; a mention and a DIRECTED
      // action-request follow the server projection in useThreadPostAttention,
      // both thread-keyed, which is the key this tag carries. The registry's
      // ten-minute TTL is gone with the distinction — it stood in for state that
      // did not exist, and a deadline was always the wrong shape for a signal
      // somebody still owes an answer to.
      registerPopout(tag, n)
    } catch {
      // Notification constructor can throw in some environments
    }
  }

  // ── Signal gate ──

  /**
   * The signal this event raises, or null if it should NOT signal.
   *
   * FE-9436: returns the REASON alongside the de-dup key, rather than leaving the caller
   * to re-derive it from the event name. The gate already knew which of the three it had
   * found — the caller was recomputing a coarser version of the same answer, and only
   * the gate can tell an approval from a mention (both arrive as `thread_message`).
   *
   * `anchor` is the post the reason points at. Only `thread_message` names one; the
   * baton's event carries no message id, which is why a hand-off still resolves to the
   * thread tail. The de-dup keys keep their exact pre-FE-9436 spellings.
   */
  function getSignal(eventName, payload) {
    const userId = useUserStore().currentUser?.id

    if (eventName === 'hub:thread_update') {
      // Baton handed to operator — PRIMARY signal
      if (payload.next_action_owner && payload.next_action_owner === userId) {
        return { key: `baton:${payload.thread_id}`, reason: BATON_FOCUS, anchor: null }
      }
      return null
    }

    if (eventName === 'hub:thread_message') {
      // Own posts are never signalled
      if (payload.from_agent_id === userId) return null
      const anchor = payload.message_id || null

      // FE-9546: `requires_action` alone is not a recipient test. `to_participant` is
      // the recipient field, and this asks the exact question the server asks — an id
      // comparison, not an interpretation, which is why it belongs here.
      //
      // FE-9586: the BROADCAST case is gone. An absent to_participant used to count,
      // read as "all recipients must act". BE-9197 rules that a broadcast
      // requires_action post is "whoever picks it up" and obligates nobody in
      // particular, and the server's directed-action query has always excluded them —
      // so this branch was contradicting the invariant every time an orchestrator
      // broadcast a directive. Such a post still lands in the bell; it no longer
      // claims the operator specifically owes an answer.
      // THREE cases, and collapsing any two of them has already caused a defect:
      //
      //   to_participant === userId  -> the operator's own ask. Full treatment.
      //   to_participant absent      -> a BROADCAST. Quiet: bell row, nothing else.
      //                                 It obligates nobody in particular (BE-9197),
      //                                 but it must still be findable (FE-9586b).
      //   to_participant set to ANY  -> somebody ELSE's ask. NOTHING, not even a bell
      //   other participant             row. FE-9546: an orchestrator directing dozens
      //                                 of these at lane agents notified the operator
      //                                 on every one. Treating this as merely "quiet"
      //                                 re-creates that spam in the bell instead of
      //                                 the popout, which is why this is spelled as
      //                                 three branches rather than one negation.
      if (payload.requires_action === true) {
        const directedElsewhere = !!payload.to_participant && payload.to_participant !== userId
        if (directedElsewhere) return null
        return {
          key: `action:${payload.message_id || payload.thread_id}`,
          reason: APPROVAL_FOCUS,
          anchor,
          quiet: !payload.to_participant,
        }
      }

      // No mention branch. See the module docblock: the server owns that verdict now,
      // and it reaches this composable through useThreadPostAttention rather than
      // through the event.
    }

    return null
  }

  function handleEvent(eventName, payload) {
    const signal = getSignal(eventName, payload)
    if (!signal) return
    const { key, reason, anchor, quiet } = signal

    // De-dupe
    if (lastSignalledKey.has(key)) return
    lastSignalledKey.add(key)

    const threadId = payload.thread_id || ''

    // FE-9289c: a handover (baton to the operator) is the "it's your call" moment —
    // distinct copy from an ordinary mention/action message. "Baton" stays the
    // code-level name; the operator sees "waiting on you".
    //
    // FE-9436: read off the REASON rather than the event name. Both the mention and the
    // approval arrive as `thread_message`, so the event name could never have told them
    // apart — which is why they shared one title and one landing. Each now says what it
    // is, and that is the only thing separating the three.
    const isHandover = reason === BATON_FOCUS
    // A quiet signal is only ever read in the bell, so it may be named for what it is
    // rather than for what the announcer would have said.
    const title = (quiet && QUIET_BELL_TITLES[reason]) || ANNOUNCER_TITLES[reason]
    // BE-9296a: name WHO is waiting, not just where. "<thread> — waiting on you" told
    // the operator the one thing they could already see; which agent is blocked is the
    // part that decides whether to answer now. The server resolves the name (it is
    // never self-declared free text) and omits it when the hander is anonymous, so the
    // thread-only wording stays as the fallback rather than rendering "undefined".
    const handedBy = isHandover ? payload.from_display_name : null
    const body = isHandover
      ? handedBy
        ? `${handedBy} is waiting on you in ${threadLabel(threadId, payload)}`
        : `${threadLabel(threadId, payload)} — waiting on you`
      : typeof payload.content === 'string'
        ? payload.content.slice(0, 80)
        : 'You have a new message'

    // FE-9289c: a HANDOVER drops a persistent entry in the notification bell, so it
    // survives navigation and the operator can Answer it later from any page. Fed by the
    // same WS event; the row is client-local (useNotificationStore _local shim), deduped
    // by a stable id so repeated events don't stack. Recorded BEFORE the presence gate —
    // the dropdown is the durable record whether or not the operator is in the Hub —
    // while the toast + browser Notification below stay gated on being AWAY.
    //
    // FE-9436: all three reasons do, per the operator ruling. A mention that disappears
    // when its toast fades is not one surface with the hand-off; it is a lesser one that
    // happens to look similar for four seconds.
    if (threadId) {
      const row = BELL_ROWS[reason]
      useNotificationStore().addNotification({
        id: `${row.prefix}:${row.keyOnPost ? anchor || threadId : threadId}`,
        type: row.type,
        title,
        body,
        // The anchor is what lets a bell row land on the exact post. Omitted rather than
        // set to null for the hand-off, whose event names none — `metadata.message_id`
        // present-but-null would read as a claim the row cannot make.
        metadata: anchor ? { thread_id: threadId, message_id: anchor } : { thread_id: threadId },
      })
    }

    // FE-9586b: a QUIET signal stops here. The durable row above is the whole of it --
    // no popout whether the tab is hidden or not, and no banner, since the projection
    // behind the banner excludes broadcasts server-side. Placed AFTER the bell write
    // and BEFORE the visibility gate on purpose: that ordering is the difference
    // between "recorded but not interruptive" and the silence this fixes.
    if (quiet) return

    // FE-9553 ruling 4(a): pop ONLY when the app is HIDDEN. The gate used to be
    // `isHubPresent` — "am I standing in the Hub pane" — which is a different
    // question, and the difference was the double notification the ruling
    // forbids: on any page other than the Hub, with the tab in front of you,
    // the old code fired an OS popout at a window you were already looking at.
    // A visible tab gets the banner alone.
    //
    // This SUPERSEDES the presence check rather than joining it. A hidden tab is
    // not "in the pane" in any meaningful sense, so the in-pane suppression is
    // subsumed by the stricter gate; ANDing the two would only re-open the case
    // where a hidden tab is silently skipped because the Hub route was last.
    if (!document.hidden) return

    // FE-9553: no toast here any more. A baton, a mention and an approval are
    // all agent-initiated and all actionable, which ruling 3 puts on the
    // banner and ruling 6 keeps off the toast — a toast is past tense about
    // the user's OWN action, and none of these three are that. The signal is
    // not lost: the durable bell row above is written before this gate, and
    // the your-turn banner row is fed independently by useYourTurnThreads out
    // of commHubStore. What goes away is the duplicate, not the notification.
    fireNotification(title, body, threadId, { reason, messageId: anchor })
  }

  // ── Mentions: announced from the SERVER's verdict, not from the event ──

  /**
   * Post ids already announced, so a re-read of the projection does not re-announce.
   *
   * Keyed on the POST, not the thread: a second mention is a second thing somebody
   * asked you (the same reason BELL_ROWS sets keyOnPost for this reason), so the
   * second one must announce even though the thread was already in the set. Keyed on
   * the post also means the projection can be re-read as often as it likes.
   */
  const announcedMentions = new Set()

  /**
   * Announce mentions as they appear in the projection.
   *
   * The event path cannot do this any more: the client no longer decides what counts
   * as a mention, so it learns about one only when the server says so. In practice
   * the sequence is: post arrives → useThreadPostAttention re-reads → a new post id
   * shows up here. That costs a round trip against the old in-event match, and buys
   * a verdict that is correct for a long body, which the old one was not.
   *
   * `immediate` covers the cold load: a mention already waiting when the page opens
   * is exactly what no live event will ever announce.
   */
  watch(
    mentions,
    (list) => {
      if (!list) return

      for (const entry of list) {
        const threadId = entry?.thread_id
        if (!threadId) continue

        // Newest first, as the projection returns them.
        const fresh = (entry.message_ids || []).filter((id) => id && !announcedMentions.has(id))
        if (!fresh.length) continue
        for (const id of fresh) announcedMentions.add(id)

        const title = ANNOUNCER_TITLES[MENTION_FOCUS]
        // The projection carries ids, not prose, and deliberately so — re-adding a
        // content excerpt to the payload would rebuild the very thing whose
        // truncation made the client's match unreliable. So the body names the
        // THREAD, which is what the operator needs in order to decide whether to
        // look now.
        const body = `You were mentioned in ${threadLabel(threadId, {})}`

        for (const id of fresh) {
          useNotificationStore().addNotification({
            id: `${BELL_ROWS[MENTION_FOCUS].prefix}:${id}`,
            type: BELL_ROWS[MENTION_FOCUS].type,
            title,
            body,
            metadata: { thread_id: threadId, message_id: id },
          })
        }

        // Ruling 4(a): the banner alone when the tab is visible. One popout per
        // THREAD, because the tag is thread-keyed — a second mention on the same
        // thread replaces rather than stacks, which is what the OS does anyway.
        if (document.hidden) {
          fireNotification(title, body, threadId, { reason: MENTION_FOCUS, messageId: fresh[0] })
        }
      }
    },
    { immediate: true },
  )

  function onThreadMessage(e) {
    handleEvent('hub:thread_message', e.detail || {})
  }

  function onThreadUpdate(e) {
    handleEvent('hub:thread_update', e.detail || {})
  }

  if (typeof window !== 'undefined') {
    window.addEventListener('hub:thread_message', onThreadMessage)
    window.addEventListener('hub:thread_update', onThreadUpdate)

    if (getCurrentScope()) {
      onScopeDispose(() => {
        window.removeEventListener('hub:thread_message', onThreadMessage)
        window.removeEventListener('hub:thread_update', onThreadUpdate)
      })
    }
  }

  return {}
}
