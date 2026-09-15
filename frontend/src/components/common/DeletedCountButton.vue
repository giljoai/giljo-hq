<template>
  <v-badge
    :content="count"
    :model-value="count > 0"
    color="warning"
    overlap
    offset-x="4"
    offset-y="4"
    data-testid="deleted-count-badge"
  >
    <v-btn
      variant="outlined"
      icon="mdi-delete-restore"
      :disabled="count === 0"
      :title="title"
      :aria-label="`View deleted ${entity}`"
      data-testid="deleted-count-btn"
      @click="$emit('click')"
    />
  </v-badge>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  count: { type: Number, default: 0 },
  entity: { type: String, default: 'items' },
})

defineEmits(['click'])

const title = computed(() =>
  props.count > 0 ? `Deleted ${props.entity} (${props.count})` : `No deleted ${props.entity}`,
)
</script>
