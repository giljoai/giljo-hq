<template>
  <BaseDialog
    v-model="isOpen"
    type="info"
    size="xl"
    icon="mdi-pencil"
    title="Edit the roadmap prompt"
    confirm-label="Copy prompt"
    @confirm="onConfirm"
  >
    <v-textarea
      v-model="text"
      variant="outlined"
      auto-grow
      rows="12"
      hide-details
      aria-label="Editable roadmap prompt"
      data-testid="roadmap-prompt-dialog-text"
    />
    <div class="rpd-note text-muted-a11y" data-testid="roadmap-prompt-dialog-note">
      Your edits are used once; they are not saved.
    </div>
  </BaseDialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import BaseDialog from '@/components/common/BaseDialog.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  promptText: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'copy'])

const text = ref(props.promptText)

const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

watch(
  () => props.modelValue,
  (open) => {
    if (open) text.value = props.promptText
  },
  { immediate: true }
)

function onConfirm() {
  emit('copy', text.value)
  emit('update:modelValue', false)
}

defineExpose({ text })
</script>

<style lang="scss" scoped>
.rpd-note {
  margin-top: 8px;
  font-size: 12px;
}
</style>
