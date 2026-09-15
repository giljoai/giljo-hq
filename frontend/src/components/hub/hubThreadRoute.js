
export const BATON_FOCUS = 'baton'
export const MENTION_FOCUS = 'mention'
export const APPROVAL_FOCUS = 'approval'

const FOCUS_REASONS = new Set([BATON_FOCUS, MENTION_FOCUS, APPROVAL_FOCUS])

export function hubThreadRoute(thread, { reason = BATON_FOCUS, messageId = null } = {}) {
  const threadId = typeof thread === 'string' ? thread : thread?.thread_id
  if (!threadId) return { path: '/hub' }
  const query = { thread: threadId }
  if (!FOCUS_REASONS.has(reason)) return { path: '/hub', query }
  query.focus = reason
  const anchor = messageId || (typeof thread === 'string' ? null : thread?.last_message?.id)
  if (anchor) query.message = anchor
  return { path: '/hub', query }
}

export function isBatonFocus(query) {
  return query?.focus === BATON_FOCUS
}

export function isActionFocus(query) {
  return FOCUS_REASONS.has(query?.focus)
}

export function focusReasonOf(query) {
  return isActionFocus(query) ? query.focus : null
}

export function focusMessageIdOf(query) {
  return query?.message || null
}

export function resolveFocusMessageId(query, selectedId, messages) {
  if (!isActionFocus(query)) return null
  if (!selectedId || selectedId !== query?.thread) return null
  if (!messages?.length) return null
  const named = focusMessageIdOf(query)
  if (named && messages.some((m) => m.message_id === named)) return named
  return messages[messages.length - 1].message_id
}
