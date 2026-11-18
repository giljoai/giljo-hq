const HOST_COOKIE = '__Host-csrf_token'
const PLAIN_COOKIE = 'csrf_token'

export function readCsrfToken(cookieString) {
  const values = new Map()
  for (const part of (cookieString || '').split(';')) {
    const separator = part.indexOf('=')
    if (separator === -1) continue
    const name = part.slice(0, separator).trim()
    if (!values.has(name)) values.set(name, part.slice(separator + 1).trim())
  }
  return values.get(HOST_COOKIE) || values.get(PLAIN_COOKIE) || null
}
