<template>
  <v-dialog v-if="proposal || builtinDiff" :model-value="true" max-width="960" scrollable persistent retain-focus>
    <v-card
      v-draggable
      class="smooth-border proposal-card"
      data-testid="template-proposal-dialog"
      :data-mode="isBuiltin ? 'builtin' : 'proposal'"
    >
      <div class="dlg-header dlg-header--primary">
        <v-icon class="dlg-icon">{{ isBuiltin ? 'mdi-update' : 'mdi-file-document-edit-outline' }}</v-icon>
        <span class="dlg-title">{{ isBuiltin ? 'Built-in updated' : 'Proposed change' }}</span>
        <v-btn
          icon
          variant="text"
          class="dlg-close"
          aria-label="Close"
          :disabled="busy"
          @click="$emit('close')"
        >
          <v-icon>mdi-close</v-icon>
        </v-btn>
      </div>

      <v-card-text>
        <dl v-if="isBuiltin" class="proposal-meta">
          <dt>Agent</dt>
          <dd data-testid="builtin-target">{{ builtinDiff.template_name }}</dd>
          <dt>Built-in version</dt>
          <dd data-testid="builtin-version">{{ builtinDiff.builtin_version }}</dd>
        </dl>
        <p v-if="isBuiltin" class="text-body-small mb-3" data-testid="builtin-explainer">
          This agent's text was copied from the built-in when the product was created, and the
          built-in has changed since. Nothing changes until you choose to use the new text.
        </p>
        <dl v-else class="proposal-meta">
          <dt>Template</dt>
          <dd data-testid="proposal-target">{{ targetName }}</dd>
          <dt>Product</dt>
          <dd data-testid="proposal-product">{{ proposal.product_name || 'All products' }}</dd>
          <dt>Reason</dt>
          <dd data-testid="proposal-reason">{{ proposal.reason }}</dd>
          <dt>Proposed by</dt>
          <dd data-testid="proposal-by">
            {{ proposal.proposed_by || 'An agent' }}, {{ formatWhen(proposal.created_at) }}
          </dd>
        </dl>

        <v-alert
          v-if="proposal?.replaced_note"
          type="info"
          variant="tonal"
          density="compact"
          class="mb-3"
          data-testid="proposal-replaced"
        >
          {{ replacedText }}
        </v-alert>

        <div class="proposal-diff-head">
          <span class="text-body-small text-muted-a11y">
            {{
              isBuiltin
                ? 'Lines marked - are in your copy only, lines marked + are in the new built-in only.'
                : 'Lines marked - are removed, lines marked + are added.'
            }}
          </span>
          <span class="diff-summary" data-testid="diff-summary">+{{ added }} -{{ removed }}</span>
        </div>
        <div class="proposal-diff smooth-border" role="list" aria-label="Full change, line by line">
          <div
            v-for="(row, i) in rows"
            :key="i"
            class="diff-row"
            :class="`diff-row--${row.type}`"
            role="listitem"
            data-testid="diff-row"
          >
            <span class="diff-marker">{{ MARKERS[row.type] }}</span>
            <span class="diff-text">{{ row.text }}</span>
          </div>
          <div v-if="!rows.length" class="diff-empty">Both versions are empty.</div>
        </div>

        <v-alert
          v-if="error"
          type="error"
          variant="tonal"
          density="compact"
          class="mt-3"
          data-testid="proposal-error"
        >
          {{ error }}
        </v-alert>
      </v-card-text>

      <div class="dlg-footer">
        <template v-if="isBuiltin">
          <v-spacer />
          <v-btn color="primary" variant="flat" data-testid="use-builtin" @click="$emit('use-builtin')">
            Use the new built-in
          </v-btn>
        </template>
        <template v-else-if="!pending">
          <v-spacer />
          <v-btn variant="text" data-testid="proposal-reject" @click="pending = 'reject'">
            Reject
          </v-btn>
          <v-btn
            color="primary"
            variant="flat"
            data-testid="proposal-apply"
            @click="pending = 'apply'"
          >
            Apply
          </v-btn>
        </template>
        <template v-else>
          <span class="proposal-confirm-text" data-testid="proposal-confirm-text">{{
            confirmText
          }}</span>
          <v-spacer />
          <v-btn
            variant="text"
            :disabled="busy"
            data-testid="proposal-confirm-cancel"
            @click="pending = null"
          >
            Back
          </v-btn>
          <v-btn
            :color="pending === 'apply' ? 'primary' : 'error'"
            variant="flat"
            :loading="busy"
            data-testid="proposal-confirm"
            @click="decide"
          >
            {{ pending === 'apply' ? 'Yes, apply' : 'Yes, reject' }}
          </v-btn>
        </template>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { lineDiff } from '@/utils/lineDiff'
import { parseErrorResponse } from '@/utils/errorMessages'
import { useTemplateProposalsStore } from '@/stores/templateProposalsStore'

const props = defineProps({
  proposal: {
    type: Object,
    default: null,
  },
  builtinDiff: {
    type: Object,
    default: null,
  },
})
const emit = defineEmits(['close', 'decided', 'use-builtin'])

const isBuiltin = computed(() => !props.proposal && !!props.builtinDiff)

const MARKERS = { same: '', add: '+', remove: '-' }

const store = useTemplateProposalsStore()
const pending = ref(null)
const busy = ref(false)
const error = ref(null)

watch(
  () => props.proposal?.id,
  () => {
    pending.value = null
    error.value = null
  },
)

const rows = computed(() => {
  if (props.proposal) return lineDiff(props.proposal.current_text, props.proposal.proposed_text)
  if (props.builtinDiff) return lineDiff(props.builtinDiff.current_text, props.builtinDiff.builtin_text)
  return []
})
const added = computed(() => rows.value.filter((r) => r.type === 'add').length)
const removed = computed(() => rows.value.filter((r) => r.type === 'remove').length)

const targetName = computed(() =>
  props.proposal?.target_kind === 'orchestrator_additions'
    ? 'Orchestrator prompt additions'
    : props.proposal?.template_name || 'Agent template',
)

function formatWhen(value) {
  const date = value ? new Date(value) : null
  return date && !Number.isNaN(date.getTime()) ? date.toLocaleString() : 'date unknown'
}

const replacedText = computed(() => {
  const note = props.proposal?.replaced_note
  if (typeof note === 'string' && note.trim()) return note
  const when = note?.saved_at ? ` saved ${formatWhen(note.saved_at)}` : ''
  const why = note?.reason ? ` ("${note.reason}")` : ''
  return `Replaced an earlier proposal${when}${why}.`
})

const applySubject = computed(() =>
  props.proposal?.target_kind === 'orchestrator_additions'
    ? 'Your orchestrator prompt additions'
    : `The ${props.proposal?.template_name || 'agent'} template's instructions`,
)

const confirmText = computed(() =>
  pending.value === 'apply'
    ? `Apply this change? ${applySubject.value} will be replaced by the proposed text.`
    : 'Reject this proposal? It is removed and the template stays as it is.',
)

async function decide() {
  const action = pending.value
  if (!action || busy.value) return
  busy.value = true
  error.value = null
  try {
    const result = await store[action](props.proposal.id)
    emit('decided', { action, proposal: props.proposal, result })
  } catch (err) {
    error.value =
      parseErrorResponse(err).message ||
      (action === 'apply' ? 'Could not apply the change.' : 'Could not reject the proposal.')
    pending.value = null
  } finally {
    busy.value = false
  }
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.proposal-meta {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 4px 16px;
  margin-bottom: 12px;
  font-size: 0.875rem;

  dt {
    color: var(--color-text-secondary);
  }

  dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
}

.proposal-diff-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 6px;
}

.diff-summary {
  font-family: $typography-font-mono;
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}

.proposal-diff {
  border-radius: $border-radius-default;
  overflow: auto;
  max-height: 55vh;
  font-family: $typography-font-mono;
  font-size: 0.8rem;
  line-height: 1.5;
}

.diff-row {
  display: flex;
  white-space: pre-wrap;
  overflow-wrap: anywhere;

  &--add {
    background: rgba($color-accent-success, 0.15);
  }

  &--remove {
    background: rgba($color-status-error, 0.15);
  }
}

.diff-marker {
  flex: 0 0 24px;
  text-align: center;
  font-weight: 700;
  user-select: none;
}

.diff-text {
  flex: 1;
  min-width: 0;
  padding-right: 8px;
}

.diff-empty {
  padding: 12px;
  color: var(--color-text-secondary);
}

.proposal-confirm-text {
  font-size: 0.875rem;
}
</style>
