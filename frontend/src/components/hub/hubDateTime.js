
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

export function threadDates(thread) {
  return {
    created: formatHubDateTime(thread?.created_at),
    lastMessage: formatHubDateTime(thread?.last_message?.created_at || thread?.last_activity_at),
  }
}
