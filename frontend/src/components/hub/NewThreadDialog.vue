<template>
  <BaseDialog
    v-model="isOpen"
    type="info"
    icon="mdi-forum-plus"
    title="New Thread"
    size="md"
    :persistent="false"
    @cancel="onCancel"
  >
    <template #default>
      <v-text-field
        v-model="subject"
        label="Name"
        variant="outlined"
        density="compact"
        hide-details="auto"
        data-testid="new-thread-subject"
        @keydown.enter="onCreate"
      />

      <p class="new-thread__hint" data-testid="new-thread-hint">
        You'll get an id to paste into any harness so agents can join.
      </p>

      <v-alert
        v-if="errorMsg"
        type="error"
        variant="tonal"
        density="compact"
        class="mt-3"
        data-testid="new-thread-error"
      >
        {{ errorMsg }}
      </v-alert>
    </template>

    <template #actions>
      <v-btn
        variant="text"
        size="small"
        class="mr-2"
        data-testid="new-thread-cancel"
        @click="onCancel"
      >
        Cancel
      </v-btn>
      <v-btn
        :disabled="!subject.trim()"
        :loading="creating"
        variant="flat"
        color="primary"
        size="small"
        data-testid="new-thread-submit"
        @click="onCreate"
      >
        Create Thread
      </v-btn>
    </template>
  </BaseDialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useCommHubStore } from '@/stores/commHubStore'
import { useProductStore } from '@/stores/products'
import { useToast } from '@/composables/useToast'
import { useClipboard } from '@/composables/useClipboard'
import { parseErrorResponse } from '@/utils/errorMessages'
import BaseDialog from '@/components/common/BaseDialog.vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:modelValue', 'created'])

const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const commHub = useCommHubStore()
const productStore = useProductStore()
const { showToast } = useToast()
const { copy } = useClipboard()

const subject = ref('')
const creating = ref(false)
const errorMsg = ref(null)

function onCancel() {
  resetForm()
  emit('update:modelValue', false)
}

function resetForm() {
  subject.value = ''
  errorMsg.value = null
}

async function onCreate() {
  if (!subject.value.trim()) return
  creating.value = true
  errorMsg.value = null
  try {
    const body = { subject: subject.value.trim() }
    if (productStore.currentProductId) body.product_id = productStore.currentProductId

    const thread = await commHub.createThread(body)

    const copied = thread?.thread_id ? await copy(thread.thread_id) : false
    showToast({
      type: 'success',
      message: copied
        ? 'Thread created — id copied, paste it into any harness.'
        : 'Thread created.',
    })

    emit('created', thread)
    emit('update:modelValue', false)
    resetForm()
  } catch (err) {
    const msg = parseErrorResponse(err).message || 'Failed to create thread.'
    errorMsg.value = msg
    showToast({ type: 'error', message: msg })
  } finally {
    creating.value = false
  }
}
</script>

<style scoped lang="scss">
.new-thread__hint {
  margin: 10px 0 0;
  font-size: 0.75rem; // 12
  color: var(--text-muted);
}
</style>
