
const FORMAT = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

export const CREATED_LABEL = 'Created'
export const LAST_MESSAGE_LABEL = 'Last msg'

export function formatHubDateTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return FORMAT.format(d)
}

export function lastMessageAt(thread) {
  const embedded = thread?.last_message?.created_at || null
  const activity = thread?.last_activity_at || null
  if (!embedded || !activity) return embedded || activity
  return new Date(activity) > new Date(embedded) ? activity : embedded
}

export function threadDates(thread) {
  return {
    created: formatHubDateTime(thread?.created_at),
    lastMessage: formatHubDateTime(lastMessageAt(thread)),
  }
}
