/**
 * hubThreadRoute.js — FE-9410
 *
 * ONE route for "a baton notification was clicked", shared by the two surfaces that
 * raise one: the app-wide banner row (SystemStatusBanner) and the Hub's own attention
 * strip (HubView). Extracted rather than written twice on the notificationRouting.js
 * precedent — the two notifications describe a single hand-off, so they must land in a
 * single place, and the only way they cannot drift apart is to have one implementation.
 *
 * The route carries two independent things, and keeping them separate is what makes the
 * fallback safe:
 *
 *   `focus` says WHY the operator arrived — a baton was handed to them. It is the
 *   authority on whether anything may be marked at all.
 *   `message` says WHICH post, when the caller knows one. FE-9418 added `Message.id` to
 *   the thread-list `last_message`, so a caller holding an enriched thread can finally
 *   name it. Before that, no source existed: the baton's own WS event and its durable
 *   bell row both carry a thread id and nothing else, and they still do.
 *
 * A caller that cannot name a post simply omits `message`, and the Hub resolves the
 * target the way it always did — the newest post once the thread is loaded. That path
 * is not a degraded mode kept alive for tidiness; the bell rows travel it every time.
 *
 * Edition scope: Both
 */

/**
 * Query value marking an arrival that came from a baton hand-off.
 *
 * FE-9436 kept the VALUE `'baton'` when the flag became a reason. It could have been
 * renamed to match the operator-facing word ("handover"), and every URL already sitting
 * in a bookmark or a durable bell row would have stopped resolving. The reason for a
 * hand-off is spelled `baton` for the same purpose the whole helper exists for: one
 * spelling, on both sides of the URL, across versions.
 */
export const BATON_FOCUS = 'baton'
/** FE-9436: the operator was named in a post. */
export const MENTION_FOCUS = 'mention'
/** FE-9436: a post is waiting on the operator's decision. */
export const APPROVAL_FOCUS = 'approval'

/**
 * Every reason an "Action needed" notification can carry.
 *
 * A CLOSED set on purpose. The reason arrives from the URL, which anyone can type, and
 * it decides whether a post gets marked at all — so it is validated against this rather
 * than trusted. An unrecognised value is not coerced to a default; see below.
 */
const FOCUS_REASONS = new Set([BATON_FOCUS, MENTION_FOCUS, APPROVAL_FOCUS])

/**
 * The route an "Action needed" notification should navigate to.
 *
 * Accepts a thread object or a bare thread id, since the banner holds the former and
 * callers with only an id should not have to fake one. With no id there is no thread to
 * open and it degrades to the plain Hub, which is the same place the multi-baton banner
 * row goes — never a broken deep link.
 *
 * `reason` defaults to the hand-off, so every caller written before FE-9436 produces its
 * pre-FE-9436 route key for key and value for value.
 *
 * The anchor comes from `messageId` when the caller has one, else from the thread's
 * `last_message`. That order is not arbitrary: `last_message` is refreshed only by a
 * thread-list read, so at event time it names whatever was newest when the list was last
 * fetched. A caller holding the live event's own `message_id` — which is every mention
 * and every approval, because `thread_message` carries one where the baton's
 * `thread_update` does not — knows the post better than the summary does.
 *
 * An unrecognised reason emits NO focus at all rather than falling back to the hand-off.
 * Defaulting would put "Waiting on you" above a post nobody handed over, which is the
 * precise defect this work order exists to close; a route that pins nothing is the
 * honest degradation, and a route that lies is not.
 */
export function hubThreadRoute(thread, { reason = BATON_FOCUS, messageId = null } = {}) {
  const threadId = typeof thread === 'string' ? thread : thread?.thread_id
  if (!threadId) return { path: '/hub' }
  const query = { thread: threadId }
  if (!FOCUS_REASONS.has(reason)) return { path: '/hub', query }
  query.focus = reason
  const anchor = messageId || (typeof thread === 'string' ? null : thread?.last_message?.id)
  // Added conditionally rather than set to null: an explicit `message=` in the URL
  // would be a claim the caller cannot make, and `?message=null` is a string.
  if (anchor) query.message = anchor
  return { path: '/hub', query }
}

/**
 * Whether a route's query says this arrival came from a BATON hand-off specifically.
 *
 * Deliberately NOT widened by FE-9436 to mean "any action reason". This predicate is
 * named after one of the three, and a caller reading it is asking about that one — a
 * mention answering true here is how a post nobody handed over acquires a "Waiting on
 * you" label. `isActionFocus` is the widened question and has its own name.
 */
export function isBatonFocus(query) {
  return query?.focus === BATON_FOCUS
}

/**
 * Whether a route's query says the operator arrived from ANY "Action needed"
 * notification — a hand-off, a mention, or an approval. This is the authority on whether
 * a post may be marked at all; `focusReasonOf` decides what the mark SAYS.
 */
export function isActionFocus(query) {
  return FOCUS_REASONS.has(query?.focus)
}

/**
 * Which of the three reasons the operator arrived for, or null when the query names none
 * it recognises. Beside the writer for the same reason as the two predicates: the code
 * that reads the URL sits with the code that wrote it, so the two cannot drift.
 */
export function focusReasonOf(query) {
  return isActionFocus(query) ? query.focus : null
}

/**
 * The post a route names, or null when it names none. Beside the writer for the same
 * reason as `isBatonFocus` — one spelling of the key, on both sides of the URL.
 *
 * Says nothing about whether the post may be MARKED; that is `isBatonFocus`'s question,
 * and the two are deliberately separate so an ordinary deep link cannot acquire a
 * "Waiting on you" label by carrying an id.
 */
export function focusMessageIdOf(query) {
  return query?.message || null
}

/**
 * Which post the operator was sent to read, or null when nothing should be marked.
 *
 * FE-9410 could only approximate this. A baton notification names a thread and nothing
 * else — its WS event and its durable bell row still carry no message id — so the target
 * was resolved as "the newest post on arrival", which is a DIFFERENT post from the one
 * that handed the baton over as soon as anything else lands in between. FE-9418 put
 * `Message.id` on the thread-list `last_message`, so the route above can now NAME the
 * post; the tail stays the answer whenever no post is named, which is every arrival from
 * the bell. One rule with a named-anchor fast path, not two competing ones.
 *
 * It lives here, beside the writer, for the reason `isBatonFocus` does: the code that
 * reads the URL should sit with the code that wrote it, so the two cannot drift.
 *
 * @param query          the current route query
 * @param selectedId     the thread actually open right now
 * @param messages       that thread's loaded timeline, oldest first
 */
export function resolveFocusMessageId(query, selectedId, messages) {
  // FE-9436 widened THIS gate from the baton to all three reasons, and changed nothing
  // below it. The three guards that follow were never about the baton — they are about
  // whether an anchor can be honoured at all — so a mention and an approval inherit them
  // as they stand rather than getting a second resolver that has to be kept in step.
  if (!isActionFocus(query)) return null
  // The flag belongs to the thread it was issued for, and it OUTLIVES the arrival: the
  // query still reads focus=baton after the operator moves on to another thread from the
  // list. Without this, the next thread they open by hand shows a post labelled "Waiting
  // on you" that nobody handed them.
  if (!selectedId || selectedId !== query?.thread) return null
  if (!messages?.length) return null
  // An anchor is honoured only if the post is actually here. One that names nothing
  // loaded — a stale bookmark, a bounded history window, a deleted post — would mark no
  // message and scroll nowhere, leaving the operator worse off than the approximation it
  // replaced. Unresolvable is therefore treated as unnamed, which is why the fallback is
  // the same line it has always been.
  const named = focusMessageIdOf(query)
  if (named && messages.some((m) => m.message_id === named)) return named
  return messages[messages.length - 1].message_id
}
