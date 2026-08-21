/**
 * notifyFailure — FE-9466
 *
 * Push a persistent notification for a save/mutation failure, carrying the
 * server's own reason when the response is structured (parseErrorResponse's
 * `isStructured`). Falls back to a safe generic message otherwise -- never a
 * raw exception, stack trace, or internal identifier.
 *
 * The id is deterministic (operation + entity + error code -- no timestamp,
 * no randomness), so the SAME failure caught at more than one layer (e.g. a
 * composable's own catch AND the view wrapper that also catches it) collapses
 * to one bell row via notificationStore.addNotification's existing
 * dedup-by-id, rather than showing the operator the same failure twice.
 */
import { parseErrorResponse } from './errorMessages'

export function notifyFailure(notificationStore, { operation, entityId = 'none', error, fallbackMessage, title = 'Action failed' }) {
  const parsed = parseErrorResponse(error)
  const message = parsed.isStructured ? parsed.message : fallbackMessage
  notificationStore.addNotification({
    id: `failure:${operation}:${entityId}:${parsed.errorCode}`,
    type: 'error',
    title,
    message,
    severity: 'error',
  })
}
