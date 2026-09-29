<!--
  Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
  Licensed under the Elastic License 2.0.
  See LICENSE in the project root for terms.
  [CE] Community Edition.
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
  successorId: {
    type: String,
    default: null,
  },
})
const emit = defineEmits(['navigate'])

const router = useRouter()
const successor = ref(null)

const label = computed(() => {
  const s = successor.value
  if (!s) return props.successorId || ''
  const alias = s.taxonomy_alias ? `${s.taxonomy_alias} — ` : ''
  return `${alias}${s.name || props.successorId}`
})

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
  router.push({ name: 'JobsViewport', query: { project: props.successorId } })
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
