/**
 * Notification preferences API — the per-user, server-side half of the
 * one-notification-model settings surface (FE-9553).
 *
 * Extracted from api.js for the same reason settingsApi.js was: that file sits
 * on the 800-line CI guardrail, so a new endpoint pair goes in its own module
 * and is spread onto `api.settings` rather than growing it.
 *
 * These live on the CURRENT USER's settings route, not the account settings
 * route, and that is deliberate: they are a personal display preference, so
 * the endpoints are authenticated as the user rather than admin-gated. The
 * toast position and duration are the exception in the other direction — they
 * stay in localStorage, because they are the one notification setting nobody
 * needs to follow them between machines.
 *
 * Edition scope: Both.
 */
import { apiClient } from './api.js'

const BASE = '/api/v1/users/me/settings/notification-preferences'

export const notificationPrefsApi = {
  getNotificationPrefs: () => apiClient.get(BASE),

  /**
   * PATCH-like PUT: send ONLY the keys being changed.
   *
   * The server treats an absent key as "leave it alone" and refuses an
   * explicit null, so a partial object is the correct payload and a full one
   * is the thing that clobbers siblings.
   */
  updateNotificationPrefs: (partial) => apiClient.put(BASE, partial),
}
