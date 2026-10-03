<template>
  <div
    class="approval-card smooth-border"
    role="alert"
    aria-live="polite"
    :style="cardStyle"
    :data-testid="'approval-card'"
  >
    <div class="approval-card__header">
      <div class="approval-card__agent-badge" :style="agentBadgeStyle">
        {{ agentInitials }}
      </div>
      <div class="approval-card__title-block">
        <div class="approval-card__title">{{ approval.reason }}</div>
        <div class="approval-card__subtitle">
          {{ approval.agent_display_name || 'agent' }} is awaiting your decision
        </div>
      </div>
    </div>

    <div v-if="contextEntries.length" class="approval-card__context">
      <div class="approval-card__context-label">Context</div>
      <dl class="approval-card__context-list">
        <template v-for="entry in contextEntries" :key="entry.key">
          <dt>{{ entry.key }}</dt>
          <dd>{{ entry.value }}</dd>
        </template>
      </dl>
    </div>

    <div v-if="error" class="approval-card__error" role="alert">
      {{ error }}
    </div>

    <div class="approval-card__actions">
      <v-btn
        v-for="(option, idx) in options"
        :key="option.id"
        :variant="idx === 0 ? 'flat' : 'text'"
        :color="idx === 0 ? 'primary' : undefined"
        :loading="pendingOptionId === option.id"
        :disabled="submitting"
        :aria-label="`Choose ${option.label}`"
        :data-testid="`approval-option-${option.id}`"
        class="approval-card__option-btn"
        @click="handleDecide(option.id)"
      >
        {{ option.label }}
      </v-btn>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useApprovalsStore } from '@/stores/useApprovalsStore'
import { useToast } from '@/composables/useToast'
import { getAgentColor } from '@/config/agentColors'
import { hexToRgba, tintedStyle } from '@/utils/colorUtils'
import { parseErrorResponse } from '@/utils/errorMessages'

const props = defineProps({
  approval: {
    type: Object,
    required: true,
    validator: (v) => v && typeof v.id === 'string' && Array.isArray(v.options),
  },
})

const emit = defineEmits(['decided', 'error'])

const approvalsStore = useApprovalsStore()
const { showToast } = useToast()

const pendingOptionId = ref(null)
const error = ref(null)

const submitting = computed(() => pendingOptionId.value !== null)

const options = computed(() => {
  return Array.isArray(props.approval?.options) ? props.approval.options : []
})

const contextEntries = computed(() => {
  const ctx = props.approval?.context
  if (!ctx || typeof ctx !== 'object') return []
  return Object.entries(ctx).map(([key, value]) => ({
    key,
    value: formatContextValue(value),
  }))
})

function formatContextValue(value) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  try {
    return JSON.stringify(value)
  } catch {
    return '[unserializable]'
  }
}

const agentColor = computed(() => {
  return getAgentColor(props.approval?.agent_display_name || '').hex
})

const agentInitials = computed(() => {
  const c = getAgentColor(props.approval?.agent_display_name || '')
  return c?.badge || '?'
})

const agentBadgeStyle = computed(() => ({ ...tintedStyle(agentColor.value), borderRadius: '8px' }))

const cardStyle = computed(() => ({
  '--smooth-border-color': hexToRgba(agentColor.value, 0.55),
  '--card-accent': hexToRgba(agentColor.value, 0.06),
  background: 'var(--card-accent)',
}))

async function handleDecide(optionId) {
  if (submitting.value) return
  pendingOptionId.value = optionId
  error.value = null
  try {
    await approvalsStore.decide(props.approval.id, optionId)
    emit('decided', { approvalId: props.approval.id, optionId })
  } catch (err) {
    const msg = parseErrorResponse(err).message || 'Failed to submit decision'
    error.value = msg
    showToast({ message: msg, type: 'error' })
    emit('error', { approvalId: props.approval.id, optionId, error: err })
  } finally {
    pendingOptionId.value = null
  }
}
</script>

<style scoped lang="scss">
.approval-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  border-radius: 12px;
}

.approval-card__header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.approval-card__agent-badge {
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 12px;
  letter-spacing: 0.5px;
  flex-shrink: 0;
}

.approval-card__title-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.approval-card__title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.35;
  color: rgba(255, 255, 255, 0.92);
  word-break: break-word;
}

.approval-card__subtitle {
  font-size: 12px;
  color: var(--text-muted);
}

.approval-card__context {
  font-size: 12px;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
}

.approval-card__context-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.approval-card__context-list {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 2px 12px;
  margin: 0;

  dt {
    color: var(--text-muted);
    font-weight: 500;
  }

  dd {
    margin: 0;
    color: rgba(255, 255, 255, 0.85);
    word-break: break-word;
  }
}

.approval-card__error {
  font-size: 12px;
  color: var(--color-status-error-light);
  padding: 6px 10px;
  border-radius: 8px;
  background: rgba(255, 138, 128, 0.1);
}

.approval-card__actions {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
}

.approval-card__option-btn {
  min-width: 96px;
  width: 100%;
  white-space: normal;
  word-break: break-word;
  text-align: left;
  height: auto;
  min-height: 40px;
  padding: 8px 14px;

  :deep(.v-btn__content) {
    white-space: normal;
    word-break: break-word;
    text-align: left;
    line-height: 1.3;
    display: block;
  }
}
</style>
