<template>
  <v-dialog
    :model-value="show"
    :max-width="isMobile ? undefined : '560'"
    :fullscreen="isMobile"
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
        <span class="dlg-title">Decision Required</span>
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
import { useDisplay } from 'vuetify'
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
const { mobile } = useDisplay()
const isMobile = computed(() => mobile.value)

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

watch(
  () => props.show,
  (open) => {
    if (open) {
      stickyApproval.value = null
      approvalsStore.fetchPending().catch(() => {})
    }
  },
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

.decision-modal-body {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
</style>
