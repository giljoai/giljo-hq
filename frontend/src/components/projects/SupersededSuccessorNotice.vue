<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.

  SupersededSuccessorNotice.vue — FE-9591

  What replaced a superseded project. `successor_project_id` has been stored on
  the row and returned by the REST API since BE-9157 and was rendered nowhere:
  the answer was captured, transmitted, and thrown away, so a superseded project
  opened the same generic card as a live one and said nothing about where the
  work went.

  Its own component rather than markup inside ProjectReviewModal.vue for
  Guardrail 1 (that file is at its size ceiling), which also gives the successor
  lookup somewhere to live -- the review payload carries the successor's ID and
  not its NAME, so naming it needs a read the modal has no other reason to make.

  Rendered ONLY for a superseded project. The normal case gains no chrome.

  Edition Scope: Both
-->
<template>
  <div
    class="superseded-notice smooth-border mt-3 pa-3 rounded d-flex align-center flex-wrap"
    data-testid="superseded-notice"
  >
    <v-icon size="16" class="superseded-notice__icon mr-2">mdi-file-replace-outline</v-icon>
    <template v-if="successorId">
      <span class="text-body-small">This project was superseded. The work moved to</span>
      <a
        class="superseded-successor-link ml-1"
        role="link"
        tabindex="0"
        data-testid="superseded-successor-link"
        @click="openSuccessor"
        @keydown.enter="openSuccessor"
      >{{ label }}</a>
    </template>
    <span v-else class="text-body-small" data-testid="superseded-notice-unknown">
      This project was superseded, but the replacement was not recorded.
    </span>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import api from '@/services/api'

const props = defineProps({
  /** The successor's project id, or null when the pointer was never recorded. */
  successorId: {
    type: String,
    default: null,
  },
})
const emit = defineEmits(['navigate'])

const router = useRouter()
const successor = ref(null)

/** Name it if the row resolved; otherwise the raw id, which is still a working link. */
const label = computed(() => {
  const s = successor.value
  if (!s) return props.successorId || ''
  const alias = s.taxonomy_alias ? `${s.taxonomy_alias} — ` : ''
  return `${alias}${s.name || props.successorId}`
})

// A failed lookup is not fatal: the notice degrades to the id rather than to a
// blank line, and the link still goes where it always went.
watch(
  () => props.successorId,
  async (id) => {
    successor.value = null
    if (!id) return
    try {
      const res = await api.projects.get(id)
      successor.value = res.data || null
    } catch (err) {
      console.error('[SupersededSuccessorNotice] successor lookup failed:', err)
    }
  },
  { immediate: true },
)

function openSuccessor() {
  if (!props.successorId) return
  router.push({ name: 'ProjectLaunch', params: { projectId: props.successorId } })
  // The host closes behind the navigation: a dialog left open over the
  // destination would trap the operator on the project they just left.
  emit('navigate')
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.superseded-notice {
  background: rgba(var(--v-theme-on-surface), 0.04);
  color: $color-text-muted;
}
.superseded-notice__icon {
  color: $color-brand-yellow;
}
.superseded-successor-link {
  color: $color-brand-yellow;
  font-weight: 600;
  cursor: pointer;
  text-decoration: none;
}
.superseded-successor-link:hover,
.superseded-successor-link:focus-visible {
  text-decoration: underline;
}
</style>
