<template>
  <v-dialog
    :model-value="show"
    max-width="560"
    persistent
    role="dialog"
    aria-labelledby="decision-modal-title"
    data-testid="decision-modal"
    @update:model-value="(v) => { if (!v) handleCancel() }"
    @keydown.esc="handleCancel"
  >
    <v-card v-draggable class="smooth-border decision-modal-card">
      <div id="decision-modal-title" class="dlg-header dlg-header--primary">
        <v-icon class="dlg-icon" icon="mdi-clipboard-check-outline" />
        <span class="dlg-title">Needs decision</span>
        <v-btn
          icon
          variant="text"
          size="small"
          class="dlg-close"
          :aria-label="'Close dialog'"
          @click="handleCancel"
        >
          <v-icon icon="mdi-close" size="18" />
        </v-btn>
      </div>

      <v-divider />

      <div class="decision-modal-body">
        <ApprovalCard
          v-if="stickyApproval"
          :approval="stickyApproval"
          data-testid="decision-modal-card"
          @decided="handleDecided"
        />
        <div v-else-if="loading" class="decision-modal-state" data-testid="decision-modal-loading">
          <v-progress-circular indeterminate size="20" width="2" color="primary" />
          <span class="text-body-small">Loading the pending decision...</span>
        </div>
        <div v-else-if="loadError" class="decision-modal-state" data-testid="decision-modal-error">
          <span class="text-body-small">
            <v-icon size="16" color="error" class="mr-1" icon="mdi-alert-circle" />
            Could not load the pending decision: {{ loadError }}
          </span>
          <v-btn variant="text" size="small" data-testid="decision-modal-retry" @click="loadPending">
            Retry
          </v-btn>
        </div>
        <p v-else class="text-body-small" data-testid="decision-modal-empty">
          No decision is waiting on this project right now. It may already have been answered.
        </p>
      </div>

      <div class="dlg-footer">
        <v-spacer />
        <v-btn variant="text" :aria-label="'Cancel'" @click="handleCancel">
          Cancel
        </v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import ApprovalCard from '@/components/orchestration/ApprovalCard.vue'
import { useApprovalsStore } from '@/stores/useApprovalsStore'

const props = defineProps({
  show: {
    type: Boolean,
    required: true,
  },
  orchestratorJobId: {
    type: String,
    default: null,
  },
})

const emit = defineEmits(['close', 'approval-decided'])

const approvalsStore = useApprovalsStore()

const liveApproval = computed(() => {
  if (!props.orchestratorJobId) return null
  return approvalsStore.findByJobId(props.orchestratorJobId)
})

const stickyApproval = ref(null)
watch(
  liveApproval,
  (a) => {
    if (a && !stickyApproval.value) stickyApproval.value = a
  },
  { immediate: true },
)

const loading = ref(false)
const loadError = ref(null)

async function loadPending() {
  loading.value = true
  loadError.value = null
  try {
    await approvalsStore.fetchPending()
  } catch {
    loadError.value = approvalsStore.error || 'the request failed'
  } finally {
    loading.value = false
  }
}

watch(
  () => props.show,
  (open, wasOpen) => {
    if (!open) return
    if (wasOpen === false) stickyApproval.value = null
    loadPending()
  },
  { immediate: true },
)

function handleCancel() {
  emit('close')
}

function handleDecided(payload) {
  emit('approval-decided', payload)
}
</script>

<style scoped lang="scss">
.decision-modal-card {
  background: rgb(var(--v-theme-surface));
}

.decision-modal-state {
  display: flex;
  align-items: center;
  gap: 8px;
}

.decision-modal-body {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
</style>
