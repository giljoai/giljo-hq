import { apiClient } from './api.js'

const BASE = '/api/v1/users/me/settings/notification-preferences'

export const notificationPrefsApi = {
  getNotificationPrefs: () => apiClient.get(BASE),

  updateNotificationPrefs: (partial) => apiClient.put(BASE, partial),
}
