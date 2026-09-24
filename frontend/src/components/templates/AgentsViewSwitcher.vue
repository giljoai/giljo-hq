<template>
  <template v-for="view in views" :key="view.value">
    <v-tooltip location="bottom">
      <template #activator="{ props: tipProps }">
        <v-btn
          v-bind="tipProps"
          :icon="view.icon"
          :variant="modelValue === view.value ? 'flat' : 'tonal'"
          :color="modelValue === view.value ? 'primary' : undefined"
          size="small"
          :aria-label="view.label"
          :data-testid="`agents-view-${view.value}`"
          :data-active="modelValue === view.value"
          @click="emit('update:modelValue', view.value)"
        />
      </template>
      {{ view.label }}
    </v-tooltip>
  </template>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: 'roster' },
  showPrompt: { type: Boolean, default: true },
})

const emit = defineEmits(['update:modelValue'])

const ALL_VIEWS = [
  { value: 'roster', label: 'Roster', icon: 'mdi-view-list' },
  { value: 'behaviour', label: 'Behaviour', icon: 'mdi-cog-outline' },
  { value: 'handover', label: 'Handover template', icon: 'mdi-swap-horizontal' },
  { value: 'prompt', label: 'Orchestrator prompt', icon: 'mdi-text-box-edit-outline' },
]

const views = computed(() => ALL_VIEWS.filter((view) => view.value !== 'prompt' || props.showPrompt))
</script>
