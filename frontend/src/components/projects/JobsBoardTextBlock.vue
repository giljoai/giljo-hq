<template>
  <section class="jb-dsec" :data-testid="`jb-drawer-${kind}`">
    <div class="jb-dsec-k">
      <span>{{ label }}</span>
      <slot name="tag" />
      <span class="jb-sp" />
      <button
        v-if="canEdit && !editing"
        ref="penRef"
        type="button"
        class="jb-pen"
        :title="`Edit ${kind}`"
        :aria-label="`Edit ${kind}`"
        :data-testid="`jb-edit-${kind}`"
        @click="start"
      >
        <v-icon size="13">mdi-pencil</v-icon>
      </button>
    </div>

    <slot v-if="!editing" />

    <div v-else class="jb-edit" @keydown.esc.stop.prevent="cancel">
      <textarea
        ref="boxRef"
        v-model="draft"
        class="jb-edit-box smooth-border"
        :class="{ 'jb-edit-box--mono': kind === 'mission' }"
        :aria-label="label"
        :aria-invalid="error ? 'true' : 'false'"
        rows="4"
        :data-testid="`jb-edit-box-${kind}`"
        @input="grow"
      />
      <p v-if="hint && !error" class="jb-edit-hint">{{ hint }}</p>
      <p v-if="error" class="jb-edit-error" role="alert">
        <v-icon size="14" class="jb-edit-error-icon" aria-hidden="true">mdi-alert-circle</v-icon>
        <span data-testid="jb-edit-error">{{ error }}</span>
      </p>
      <div class="jb-edit-actions">
        <v-btn variant="text" size="small" data-testid="jb-edit-cancel" @click="cancel">Cancel</v-btn>
        <v-btn
          color="primary"
          variant="flat"
          size="small"
          :disabled="saving || !canSave"
          data-testid="jb-edit-save"
          @click="submit"
        >
          Save
        </v-btn>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, nextTick } from 'vue'

const props = defineProps({
  kind: { type: String, required: true },
  label: { type: String, required: true },
  text: { type: String, default: '' },
  canEdit: { type: Boolean, default: true },
  canSave: { type: Boolean, default: true },
  allowEmpty: { type: Boolean, default: false },
  hint: { type: String, default: '' },
  save: { type: Function, required: true },
})

const editing = ref(false)
const draft = ref('')
const error = ref('')
const saving = ref(false)
const penRef = ref(null)
const boxRef = ref(null)

function grow() {
  const el = boxRef.value
  if (el && el.scrollHeight > 0) {
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }
}

async function start() {
  draft.value = props.text
  error.value = ''
  editing.value = true
  await nextTick()
  boxRef.value?.focus()
  grow()
}

async function close() {
  editing.value = false
  await nextTick()
  penRef.value?.focus()
}

function cancel() {
  error.value = ''
  return close()
}

async function submit() {
  if (!props.canSave || saving.value) return
  if (!props.allowEmpty && !draft.value) {
    error.value = 'Description is required'
    return
  }
  saving.value = true
  error.value = ''
  try {
    await props.save(draft.value)
  } catch (err) {
    error.value = err?.response?.data?.error || err?.message || 'Failed to save project'
    return
  } finally {
    saving.value = false
  }
  await close()
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.jb-dsec {
  padding: 12px 0;

  & + & {
    box-shadow: inset 0 1px 0 0 $color-border-tertiary;
  }
}

.jb-dsec-k {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.62rem;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: $color-text-secondary;
  margin-bottom: 6px;
  min-height: 24px;
}

.jb-sp {
  flex: 1;
}

.jb-pen {
  flex: none;
  display: inline-grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: $border-radius-sharp;
  background: none;
  border: 0;
  padding: 0;
  color: $color-text-tertiary;
  cursor: pointer;

  &:hover,
  &:focus-visible {
    color: $color-brand-yellow;
    background: rgba($color-brand-yellow, 0.08);
  }
}

.jb-edit-box {
  display: block;
  width: 100%;
  min-height: 5.5rem;
  max-height: 22rem;
  overflow-y: auto;
  resize: vertical;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 0;
  border-radius: $border-radius-md;
  background: $elevation-elevated;
  color: $color-text-primary;
  font: inherit;
  font-size: 0.82rem;
  line-height: 1.6;

  &--mono {
    font-family: $typography-font-mono;
    font-size: 0.74rem;
  }

  &:focus-visible {
    outline: 2px solid $color-brand-yellow;
    outline-offset: 1px;
  }
}

.jb-edit-hint,
.jb-edit-error {
  margin: 6px 0 0;
  font-size: 0.72rem;
}

.jb-edit-hint {
  color: $color-text-secondary;
}

.jb-edit-error {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  color: $color-text-primary;
}

.jb-edit-error-icon {
  flex: none;
  color: $color-status-error;
}

.jb-edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
</style>
