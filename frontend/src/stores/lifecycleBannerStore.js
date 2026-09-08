// Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
// Licensed under the Elastic License 2.0.
// See LICENSE in the project root for terms.
// [CE] Community Edition.

/**
 * lifecycleBannerStore.js — FE-9538
 *
 * Client-armed, ephemeral rows for the "a project just crossed a lifecycle
 * moment" banner (staged / activated / implementation launched), fed by the
 * router's project-event handlers (see stores/eventRoutes/projectEventRoutes.js).
 * Not a Notification row (neither CE's background_tasks family nor SaaS's
 * banner_emitter family) -- this extends the SAME approval-style ephemeral-row
 * pattern SystemStatusBanner already uses for pendingApprovals/yourTurnThreads:
 * a live read of transient state, not a fetched/persisted notification.
 *
 * Ruling 19: this store only RECORDS that a moment happened. It never
 * navigates by itself -- SystemStatusBanner renders a button per row and the
 * user clicks it.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useProjectStore } from '@/stores/projects'
import { useSettingsStore } from '@/stores/settings'

/** Never hold more than this many lifecycle rows at once (oldest drops first). */
export const MAX_LIFECYCLE_ROWS = 3

/** Canned, past-tense copy per moment -- never agent-authored prose. Exposed
 * to callers only through `momentLabel()` below, never imported directly. */
const LIFECYCLE_MOMENT_LABELS = {
  staging_complete: 'is ready to launch',
  activated: 'has started',
  implementation_launched: 'has started implementation',
}

export const useLifecycleBannerStore = defineStore('lifecycleBanner', () => {
  const rows = ref([])

  /**
   * Record a lifecycle moment for a project. Unknown moments are ignored
   * (defensive -- a future WS payload shape should never crash the banner).
   * A project already carrying a row is REPLACED, not stacked: the same
   * project moving staged -> launched in one session should show its ONE
   * current moment, not a growing pile of stale ones.
   *
   * `taxonomyAlias`/`title` are resolved from projectStore's cache -- the
   * WS payloads for these events do not carry them. When the project was
   * never opened this session (cache miss), the row still renders with a
   * generic "A project" fallback rather than being dropped.
   */
  function announce({ projectId, moment }) {
    if (!projectId || !LIFECYCLE_MOMENT_LABELS[moment]) return

    // FE-9553: the "Lifecycle events" preference gates the BANNER, and only the
    // banner. The durable bell row is written on the event path regardless
    // (announceLifecycleMoment in projectEventRoutes), so "off" means bell-only
    // rather than gone -- ruling 1, and the difference between a preference and
    // a control that lies.
    //
    // Gated HERE, at the source, rather than in SystemStatusBanner's row
    // filter: one decision per preference, read by every display, instead of a
    // filter per consumer that can drift.
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
