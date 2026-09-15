
const SHORT_SHA_LENGTH = 8

export function shortSha(sha, length = SHORT_SHA_LENGTH) {
  if (!sha || typeof sha !== 'string') return ''
  return sha.slice(0, length)
}

export function commitTitle(commit) {
  if (!commit || typeof commit !== 'object') return ''
  const message = typeof commit.message === 'string' ? commit.message.trim() : ''
  if (message) return message
  return shortSha(commit.sha)
}
