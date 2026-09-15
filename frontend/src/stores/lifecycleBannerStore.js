// Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
// Licensed under the Elastic License 2.0.
// See LICENSE in the project root for terms.
// [CE] Community Edition.

import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useProjectStore } from '@/stores/projects'
import { useSettingsStore } from '@/stores/settings'

export const MAX_LIFECYCLE_ROWS = 3

const LIFECYCLE_MOMENT_LABELS = {
  staging_complete: 'is ready to launch',
  activated: 'has started',
  implementation_launched: 'has started implementation',
}

export const useLifecycleBannerStore = defineStore('lifecycleBanner', () => {
  const rows = ref([])

  function announce({ projectId, moment }) {
    if (!projectId || !LIFECYCLE_MOMENT_LABELS[moment]) return

    if (!useSettingsStore().bannerLifecycleEnabled) return

    const project = useProjectStore().projectById(projectId)

    rows.value = [
      {
        id: `${projectId}:${moment}:${Date.now()}`,
        projectId,
        moment,
        taxonomyAlias: project?.taxonomy_alias || null,
        title: project?.name || null,
      },
      ...rows.value.filter((row) => row.projectId !== projectId),
    ].slice(0, MAX_LIFECYCLE_ROWS)
  }

  function dismiss(id) {
    rows.value = rows.value.filter((row) => row.id !== id)
  }

  function momentLabel(moment) {
    return LIFECYCLE_MOMENT_LABELS[moment] || 'has updated'
  }

  return { rows, announce, dismiss, momentLabel }
})
