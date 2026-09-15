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
