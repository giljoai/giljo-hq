// Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
// Licensed under the Elastic License 2.0.
// See LICENSE in the project root for terms.
// [CE] Community Edition.

import { useLifecycleBannerStore } from '@/stores/lifecycleBannerStore'

export function useLifecycleBannerNav(router) {
  const lifecycleBannerStore = useLifecycleBannerStore()

  function openLifecycleBanner(row) {
    if (!row?.projectId) return
    router.push({ name: 'JobsViewport', query: { project: row.projectId, detail: '1' } })
  }

  return { lifecycleBannerStore, openLifecycleBanner }
}
