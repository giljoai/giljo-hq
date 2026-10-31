<template>
  <div class="jb-done" data-testid="jobs-done-group">
    <div class="jb-done-row">
      <button
        type="button"
        class="jb-done-h"
        :aria-expanded="open"
        data-testid="jobs-done-group-toggle"
        @click="open = !open"
      >
        <v-icon size="14">{{ open ? 'mdi-chevron-down' : 'mdi-chevron-right' }}</v-icon>
        <span class="jb-done-k">Done, not reviewed</span>
        <span class="jb-done-n" data-testid="jobs-done-group-count">({{ count }})</span>
      </button>
      <v-tooltip v-if="projectIds.length" location="top">
        <template #activator="{ props: tip }">
          <button
            v-bind="tip"
            type="button"
            class="jb-done-all"
            data-testid="jobs-done-group-mark-all"
            @click="confirming = true"
          >
            Mark all reviewed
          </button>
        </template>
        Mark every project in this section as reviewed. Nothing is deleted.
      </v-tooltip>
    </div>
    <div v-if="open" class="jb-done-body" data-testid="jobs-done-group-cards">
      <slot />
    </div>

    <v-dialog v-model="confirming" max-width="460" :persistent="busy">
      <v-card v-if="confirming" class="smooth-border" data-testid="jobs-done-mark-all-confirm">
        <div class="dlg-header">
          <span class="dlg-title">Mark all reviewed?</span>
          <v-btn icon variant="text" size="small" class="dlg-close" aria-label="Close dialog" :disabled="busy" @click="confirming = false">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </div>
        <v-divider />
        <v-card-text data-testid="jobs-done-mark-all-body">{{ confirmText }}</v-card-text>
        <v-divider />
        <div class="dlg-footer">
          <v-spacer />
          <v-btn variant="text" :disabled="busy" data-testid="jobs-done-mark-all-cancel" @click="confirming = false">Cancel</v-btn>
          <v-btn color="primary" variant="flat" :loading="busy" data-testid="jobs-done-mark-all-submit" @click="markAll">
            Mark all reviewed
          </v-btn>
        </div>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useProjectStore } from '@/stores/projects'
import { useToast } from '@/composables/useToast'
import { parseErrorResponse } from '@/utils/errorMessages'

const MARK_ALL_CAP = 500

const props = defineProps({
  count: { type: Number, required: true },
  projectIds: { type: Array, default: () => [] },
  productName: { type: String, default: '' },
})
const emit = defineEmits(['changed'])

const projectStore = useProjectStore()
const { showToast } = useToast()
const open = ref(false)
const confirming = ref(false)
const busy = ref(false)

const noun = (n) => `${n} ${n === 1 ? 'project' : 'projects'}`
const confirmText = computed(() => {
  const where = props.productName ? ` in ${props.productName}` : ''
  return `Mark ${noun(props.projectIds.length)}${where} as reviewed? They leave this list. Nothing is deleted.`
})

async function markAll() {
  busy.value = true
  try {
    const { marked, skipped } = await projectStore.markProjectsReviewed(props.projectIds.slice(0, MARK_ALL_CAP))
    confirming.value = false
    if (skipped.length) {
      showToast({
        message: `${noun(marked)} marked reviewed. ${skipped.length} skipped.`,
        type: 'warning',
      })
    } else {
      showToast({ message: `${noun(marked)} marked reviewed.`, type: 'success' })
    }
    emit('changed')
  } catch (err) {
    confirming.value = false
    showToast({ message: parseErrorResponse(err).message || 'Could not mark the projects reviewed.', type: 'error' })
  } finally {
    busy.value = false
  }
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.jb-done {
  margin-top: 8px;
}

.jb-done-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.jb-done-all {
  background: none;
  border: 0;
  padding: 6px 0;
  cursor: pointer;
  color: $color-text-secondary;
  font-size: 0.78rem;
  text-decoration: underline;

  &:hover,
  &:focus-visible {
    color: $color-brand-yellow;
  }
}

.jb-done-h {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: none;
  border: 0;
  padding: 6px 0;
  cursor: pointer;
  color: $color-text-secondary;
  font-size: 0.78rem;

  &:hover,
  &:focus-visible {
    color: $color-brand-yellow;
  }
}

.jb-done-k {
  letter-spacing: 0.02em;
}

.jb-done-n {
  font-family: $typography-font-mono;
}

.jb-done-body {
  margin-top: 10px;
}
</style>
