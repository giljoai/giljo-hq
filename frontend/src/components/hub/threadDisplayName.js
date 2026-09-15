
export function threadDisplayName(thread, payload) {
  return (
    thread?.subject ||
    thread?.title ||
    payload?.subject ||
    payload?.chat_id ||
    thread?.chat_id ||
    'a thread'
  )
}
