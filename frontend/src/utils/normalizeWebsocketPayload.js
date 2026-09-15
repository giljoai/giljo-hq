export function normalizeWebsocketPayload(rawEvent) {
  if (!rawEvent || typeof rawEvent !== 'object') {
    return { type: undefined, payload: {} }
  }

  const { type, ...rest } = rawEvent

  if (rest.data && typeof rest.data === 'object' && !Array.isArray(rest.data)) {
    return { type, payload: { ...rest, ...rest.data } }
  }

  return { type, payload: rest }
}
