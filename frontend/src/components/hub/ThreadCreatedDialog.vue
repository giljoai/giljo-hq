<template>
  <BaseDialog
    v-model="isOpen"
    type="success"
    icon="mdi-check-circle-outline"
    title="Thread created"
    :size="460"
    :persistent="false"
    @cancel="onClose"
  >
    <template #default>
      <p class="thread-created__lead" data-testid="thread-created-lead">
        Copy this and tell agents to message you in this thread.
      </p>

      <div class="thread-created__id-card smooth-border" data-testid="thread-created-id-card">
        <div v-if="chatId" class="thread-created__chat-id" data-testid="thread-created-chat-id">
          {{ chatId }}
        </div>
        <div class="thread-created__id-row">
          <code class="thread-created__thread-id" data-testid="thread-created-thread-id">
            {{ threadId }}
          </code>
          <v-btn
            icon
            variant="text"
            size="small"
            class="thread-created__copy-btn"
            :title="copied ? 'Copied' : 'Copy thread id'"
            data-testid="thread-created-copy"
            @click="onCopy"
          >
            <v-icon size="18">{{ copied ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>
          </v-btn>
        </div>
      </div>
    </template>

    <template #actions>
      <v-checkbox
        v-model="dontShowAgain"
        label="Don't show again"
        density="compact"
        hide-details
        class="thread-created__dont-show"
        data-testid="thread-created-dont-show"
      />
      <v-spacer />
      <v-btn
        variant="flat"
        color="primary"
        size="small"
        data-testid="thread-created-done"
        @click="onClose"
      >
        Done
      </v-btn>
    </template>
  </BaseDialog>
</template>

<script>
const HIDE_HINT_KEY = 'giljo.hub.threadCreatedHintHidden'

export function isThreadCreatedHintHidden() {
  try {
    return localStorage.getItem(HIDE_HINT_KEY) === '1'
  } catch {
    return false
  }
}
</script>

<script setup>
import { ref, computed } from 'vue'
import { useClipboard } from '@/composables/useClipboard'
import { useToast } from '@/composables/useToast'
import BaseDialog from '@/components/common/BaseDialog.vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
  thread: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['update:modelValue'])

const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const { copy, copied } = useClipboard()
const { showToast } = useToast()

const dontShowAgain = ref(false)

const threadId = computed(() => props.thread?.thread_id || '')
const chatId = computed(() => {
  const raw = props.thread?.chat_id
  if (!raw) return ''
  const match = String(raw).match(/(\d+)$/)
  if (match) return `CHT-${String(match[1]).padStart(4, '0')}`
  return `CHT-${raw}`
})

async function onCopy() {
  if (!threadId.value) return
  const ok = await copy(threadId.value)
  if (ok) {
    showToast({ type: 'success', message: 'Thread id copied.' })
  } else {
    showToast({ type: 'error', message: 'Browser blocked the copy — select and copy manually.' })
  }
}

function onClose() {
  if (dontShowAgain.value) {
    try {
      localStorage.setItem(HIDE_HINT_KEY, '1')
    } catch {
      // localStorage unavailable (private mode) — non-fatal, hint just keeps showing.
    }
  }
  emit('update:modelValue', false)
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;
@use '../../styles/variables' as v;

.thread-created__lead {
  font-size: 0.85rem;
  color: var(--text-secondary);
  margin-bottom: v.$spacing-md;
  line-height: 1.5;
}

.thread-created__id-card {
  background: $elevation-flat;
  border-radius: $border-radius-default;
  padding: v.$spacing-sm v.$spacing-md;
}

.thread-created__chat-id {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  color: $color-brand-yellow;
  margin-bottom: v.$spacing-xs;
}

.thread-created__id-row {
  display: flex;
  align-items: center;
  gap: v.$spacing-sm;
}

.thread-created__thread-id {
  flex: 1;
  min-width: 0;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.74rem;
  color: var(--text-secondary);
  word-break: break-all;
  background: transparent;
}

.thread-created__copy-btn {
  flex-shrink: 0;
}

.thread-created__dont-show {
  flex: 0 1 auto;
  :deep(.v-label) {
    font-size: 0.8rem;
    opacity: 0.9;
  }
}
</style>
