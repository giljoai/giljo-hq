import { parseErrorResponse } from '@/utils/errorMessages'

export const SIGN_IN_WAIT_COPY = {
  waiting: (remaining) =>
    `Too many sign-in attempts. Please wait ${formatWait(remaining)} and try again.`,
  announceStart: (remaining) =>
    `Too many sign-in attempts. You can try again in ${formatWait(remaining)}.`,
  announceTick: (remaining) => `You can try again in ${formatWait(remaining)}.`,
  announceDone: 'You can sign in again now.',
}

const SIGN_IN_WAIT_FALLBACK_SECONDS = 60
const SIGN_IN_WAIT_MAX_SECONDS = 900
export const SIGN_IN_WAIT_ANNOUNCE_EVERY_SECONDS = 10

const LOCKED_MESSAGE_PREFIX = 'too many failed login attempts'
const LOCKED_ERROR_CODE = 'ACCOUNT_LOCKED'

function formatWait(seconds) {
  const total = Math.max(0, Math.ceil(seconds))
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  const unit = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`
  if (minutes === 0) return unit(rest, 'second')
  if (rest === 0) return minutes === 1 ? 'a minute' : unit(minutes, 'minute')
  return `${unit(minutes, 'minute')} ${unit(rest, 'second')}`
}

export function isAccountLocked429(error) {
  const { errorCode, message } = parseErrorResponse(error)
  return errorCode === LOCKED_ERROR_CODE || message.toLowerCase().startsWith(LOCKED_MESSAGE_PREFIX)
}

export function waitSecondsFrom429(error) {
  const headers = error?.response?.headers
  const raw = headers?.['retry-after'] ?? headers?.get?.('retry-after')
  const seconds = Number(raw)
  if (raw === undefined || raw === null || raw === '' || !Number.isFinite(seconds) || seconds < 0) {
    return SIGN_IN_WAIT_FALLBACK_SECONDS
  }
  return Math.min(Math.max(1, Math.ceil(seconds)), SIGN_IN_WAIT_MAX_SECONDS)
}
