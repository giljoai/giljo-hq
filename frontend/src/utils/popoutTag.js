
const PREFIX = 'giljo-hub'

export function popoutTag(reason, threadId) {
  return `${PREFIX}:${reason || 'baton'}:${threadId || 'unknown'}`
}
