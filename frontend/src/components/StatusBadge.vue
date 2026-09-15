<template>
  <span
    class="status-badge"
    :style="badgeStyle"
    :aria-label="`Project status: ${statusLabel}`"
  >
    {{ statusLabel }}
  </span>
</template>

<script setup>
import { computed, toRef } from 'vue'

import { hexToRgba } from '@/utils/colorUtils'
import { useProjectStatusesStore } from '@/stores/projectStatusesStore'
import { useStatusBadgeMeta } from '@/composables/useStatusBadgeMeta'

const props = defineProps({
  status: {
    type: String,
    required: true,
  },
})

const statusesStore = useProjectStatusesStore()

const { meta, statusLabel, colorHex } = useStatusBadgeMeta(
  toRef(props, 'status'),
  statusesStore,
)

const badgeStyle = computed(() => ({
  background: hexToRgba(colorHex.value, 0.15),
  color: colorHex.value,
  borderRadius: '8px',
}))

defineExpose({ statusLabel, meta, colorHex })
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;
.status-badge {
  display: inline-flex;
  align-items: center;
  // Square-cornered pill per design-system-sample-v2.html (tinted badge).
  // No CSS `border` — tinted background carries the visual weight.
  border-radius: 8px;
  font-size: 0.68rem;
  font-weight: 600;
  padding: 3px 10px;
  white-space: nowrap;
  line-height: 1.4;
  user-select: none;
}
</style>
