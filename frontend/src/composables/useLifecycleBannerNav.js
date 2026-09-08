// Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
// Licensed under the Elastic License 2.0.
// See LICENSE in the project root for terms.
// [CE] Community Edition.

/**
 * useLifecycleBannerNav.js — FE-9538
 *
 * SystemStatusBanner's lifecycle-banner wiring, extracted to keep that
 * component under the 800-line guardrail (the same reason
 * useApprovalBannerState.js and useYourTurnThreads.js already live outside
 * it). Owns the store handle + the ONE navigation action a row's click can
 * trigger -- never auto-navigates on its own: this only runs
 * from a user click the parent template wires up.
 */
import { useLifecycleBannerStore } from '@/stores/lifecycleBannerStore'

export function useLifecycleBannerNav(router) {
  const lifecycleBannerStore = useLifecycleBannerStore()

  function openLifecycleBanner(row) {
    if (!row?.projectId) return
    router.push({
      name: 'ProjectLaunch',
      params: { projectId: row.projectId },
      query: { tab: 'jobs', via: 'jobs' },
    })
  }

  return { lifecycleBannerStore, openLifecycleBanner }
}
