
const PREFIX = 'giljo-hub'

export function popoutTag(reason, entityId, userId) {
  return `${PREFIX}:${reason || 'baton'}:${entityId || 'unknown'}:${userId || 'anyone'}`
}
