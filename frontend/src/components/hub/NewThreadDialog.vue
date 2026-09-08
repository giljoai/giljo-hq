<!--
  NewThreadDialog.vue — FE-9289c

  A name and one hint. The raw project_id / product_id fields are gone: a general
  thread does not need them, and a project thread is created BY the project, never by
  someone pasting a UUID into a text box here.

  On create the thread id goes straight to the clipboard, because handing it to an
  agent is the only reason the operator opened this dialog.
-->
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
    // FE-9588 — carry the viewed product. Since Headless-S4 demoted the active
    // product to a mere default, a create naming no product on a tenant owning
    // more than one is refused with PRODUCT_AMBIGUOUS. That refusal is written for
    // an agent, whose remedy is to retry naming one; a dialog cannot retry, so it
    // states the product up front. `currentProductId` is the VIEWED TAB (not
    // `activeProduct`, the tenant-wide default) — the Hub is tabbed by product, so
    // what the operator is looking at is the unambiguous answer.
    //
    // Omitted when there is no viewed tab: a tenant owning zero products is ruling
    // 1's stated exception and the server resolves it to a standalone thread.
    // NOT defaulted inside `commHub.createThread`, deliberately — the other caller
    // (useProjectBoundThread) passes a project_id, and the server derives the
    // product from THAT project on purpose, "regardless of which tab the caller
    // happens to be viewing". A store-level default would silently override it.
    const body = { subject: subject.value.trim() }
    if (productStore.currentProductId) body.product_id = productStore.currentProductId

    const thread = await commHub.createThread(body)

    // The id is the point of the dialog — put it on the clipboard rather than making
    // the operator go and find it. A blocked clipboard is not a failed create, so it
    // downgrades the message instead of erroring: the id is still shown afterwards.
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
    const msg = err?.response?.data?.detail || err?.message || 'Failed to create thread.'
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
