<template>
  <BaseDialog
    v-model="isOpen"
    type="info"
    icon="mdi-shape-plus"
    title="Add Project Type"
    size="md"
    @cancel="close"
  >
    <v-form ref="formRef" v-model="formValid">
      <v-text-field
        v-model="abbreviation"
        label="Abbreviation"
        hint="2-4 uppercase letters (e.g. DEV, TST)"
        persistent-hint
        counter="4"
        :rules="abbreviationRules"
        class="mb-3"
        aria-label="Type abbreviation"
        @update:model-value="abbreviation = ($event || '').toUpperCase()"
      />

      <v-text-field
        v-model="label"
        label="Label"
        hint="Display name (e.g. DevOps, Testing)"
        persistent-hint
        counter="50"
        :rules="labelRules"
        class="mb-3"
        aria-label="Type label"
      />

      <div class="mb-3">
        <label class="text-body-small text-muted-a11y d-block mb-1">Color</label>
        <div class="d-flex align-center ga-2 flex-wrap">
          <v-btn
            v-for="swatch in colorSwatches"
            :key="swatch"
            icon
            size="small"
            :style="{
              backgroundColor: swatch,
              border:
                color === swatch
                  ? '3px solid white'
                  : '1px solid rgba(255,255,255,0.3)' /* exempt: dynamic color picker UI */,
              boxShadow: color === swatch ? '0 0 0 2px ' + swatch : 'none',
            }"
            :aria-label="'Select color ' + swatch"
            @click="color = swatch"
          />
          <v-text-field
            v-model="color"
            density="compact"
            variant="outlined"
            class="color-input-field"
            :rules="colorRules"
            hide-details
            aria-label="Custom hex color"
          >
            <template #prepend-inner>
              <div
                :style="{
                  backgroundColor: color,
                  width: '18px',
                  height: '18px',
                  borderRadius: '50%',
                  flexShrink: 0,
                }"
              />
            </template>
          </v-text-field>
        </div>
      </div>

      <v-alert type="info" variant="tonal" density="compact" class="mt-4">
        <div class="d-flex align-center">
          <div
            :style="{
              backgroundColor: color,
              width: '14px',
              height: '14px',
              borderRadius: '50%',
              marginRight: '8px',
              flexShrink: 0,
            }"
          />
          <strong>{{ abbreviation || 'ABBR' }} - {{ label || 'Label' }}</strong>
        </div>
      </v-alert>

      <v-alert
        v-if="submitError"
        type="error"
        variant="tonal"
        density="compact"
        class="mt-3"
        closable
        @click:close="submitError = null"
      >
        {{ submitError }}
      </v-alert>
    </v-form>

    <template #actions>
      <v-spacer />
      <v-btn variant="text" @click="close">Cancel</v-btn>
      <v-btn
        color="primary"
        variant="flat"
        :disabled="!formValid || submitting"
        :loading="submitting"
        @click="handleSubmit"
      >
        Add Type
      </v-btn>
    </template>
  </BaseDialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import api from '@/services/api'
import BaseDialog from '@/components/common/BaseDialog.vue'
import {
  PROJECT_TYPE_COLOR_SWATCHES,
  DEFAULT_SWATCH_COLOR,
  RESERVED_TASK_TYPE_ABBR,
} from '@/utils/constants'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'type-created'])

const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const formRef = ref(null)
const formValid = ref(false)
const submitting = ref(false)
const submitError = ref(null)

const abbreviation = ref('')
const label = ref('')
const color = ref(DEFAULT_SWATCH_COLOR)

const colorSwatches = PROJECT_TYPE_COLOR_SWATCHES

const abbreviationRules = [
  (v) => !!v || 'Abbreviation is required',
  (v) => /^[A-Z]{2,4}$/.test(v) || 'Must be 2-4 uppercase letters',
  (v) => v !== RESERVED_TASK_TYPE_ABBR || `${RESERVED_TASK_TYPE_ABBR} is reserved for tasks`,
]

const labelRules = [
  (v) => !!v || 'Label is required',
  (v) => (v && v.length <= 50) || 'Max 50 characters',
]

const colorRules = [(v) => /^#[0-9A-Fa-f]{6}$/.test(v) || 'Must be valid hex (e.g. #FF5722)']

function close() {
  emit('update:modelValue', false)
  resetForm()
}

function resetForm() {
  abbreviation.value = ''
  label.value = ''
  color.value = DEFAULT_SWATCH_COLOR
  submitError.value = null
  submitting.value = false
}

async function handleSubmit() {
  if (!formValid.value || submitting.value) return

  submitting.value = true
  submitError.value = null

  try {
    const { data } = await api.taxonomyTypes.create({
      abbreviation: abbreviation.value,
      label: label.value,
      color: color.value,
    })
    emit('type-created', data)
    close()
  } catch (err) {
    const detail = err.response?.data?.detail
    submitError.value = detail || err.message || 'Failed to create project type'
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.color-input-field {
  max-width: 120px;
}
</style>
