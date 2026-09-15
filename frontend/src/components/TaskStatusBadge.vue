<template>
  <span
    class="task-status-badge smooth-border"
    :style="badgeStyle"
    :aria-label="`Task status: ${statusLabel}`"
  >
    {{ statusLabel }}
  </span>
</template>

<script setup>
import { computed, toRef } from 'vue'

import { hexToRgba } from '@/utils/colorUtils'
import { useTaskStatusesStore } from '@/stores/taskStatusesStore'
import { useStatusBadgeMeta } from '@/composables/useStatusBadgeMeta'

const props = defineProps({
  status: {
    type: String,
    required: true,
  },
})

const statusesStore = useTaskStatusesStore()

const { meta, statusLabel, colorHex } = useStatusBadgeMeta(
  toRef(props, 'status'),
  statusesStore,
)

const badgeStyle = computed(() => ({
  background: hexToRgba(colorHex.value, 0.15),
  color: colorHex.value,
  borderRadius: '8px',
  '--smooth-border-color': hexToRgba(colorHex.value, 0.35),
}))

defineExpose({ statusLabel, meta, colorHex })
</script>

<style lang="scss" scoped>
.task-status-badge {
  display: inline-flex;
  align-items: center;
  // Square-cornered pill per design-system-sample-v2.html (tinted badge).
  // `smooth-border` from main.scss carries the inset border (no CSS `border`
  // on a rounded element).
  border-radius: 8px;
  font-size: 0.68rem;
  font-weight: 600;
  padding: 3px 10px;
  white-space: nowrap;
  line-height: 1.4;
  user-select: none;
}
</style>
