<!--
  DeletedCountButton.vue — FE-9368

  The trash icon button that opens a "deleted items" recovery surface, with the count
  carried by a small alert dot instead of a text label.

  Why it is a component and not two copies: the Hub and Projects render the SAME
  control, and the operator asked for the two pages to stay consistent. Two
  hand-maintained copies of "consistent" drift; one component used by both cannot.

  The dot is Vuetify's <v-badge>, the same element the notification bell uses, so the
  count reads identically in both places and no new colour enters the design system.
-->
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
  /** How many deleted items are recoverable. Zero disables the button. */
  count: { type: Number, default: 0 },
  /** Plural noun for the tooltip and the aria-label, e.g. 'threads'. */
  entity: { type: String, default: 'items' },
})

defineEmits(['click'])

// The count still reads out in words for screen readers and on hover; the dot is the
// glanceable half, not the only half.
const title = computed(() =>
  props.count > 0 ? `Deleted ${props.entity} (${props.count})` : `No deleted ${props.entity}`,
)
</script>
