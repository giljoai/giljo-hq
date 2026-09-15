<template>
  <v-dialog
    v-model="isOpen"
    :max-width="maxWidth"
    :persistent="persistent"
    :scrollable="scrollable"
    z-index="2500"
    @update:model-value="handleDialogChange"
  >
    <v-card v-draggable class="base-dialog-card smooth-border" elevation="24">
      <div :class="headerClasses">
        <slot name="headerIcon">
          <v-icon v-if="showIcon" class="dlg-icon" :icon="iconName" />
        </slot>
        <span class="dlg-title">{{ title }}</span>
        <slot name="titleAppend" />
        <v-btn
          icon
          variant="text"
          size="small"
          class="dlg-close"
          aria-label="Close dialog"
          :disabled="loading"
          @click="handleCancel"
        >
          <v-icon icon="mdi-close" size="18" />
        </v-btn>
      </div>

      <v-divider />

      <v-card-text class="pa-4">
        <v-alert
          v-if="message && !$slots.default"
          :type="type"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ message }}
        </v-alert>

        <slot />

        <v-text-field
          v-if="confirmText"
          v-model="confirmInput"
          :label="`Type ${confirmText} to confirm`"
          variant="outlined"
          :hint="`Type the word ${confirmText} to enable the confirm button`"
          persistent-hint
          :placeholder="confirmText"
          class="mt-4"
        />

        <v-checkbox
          v-if="confirmCheckbox"
          v-model="checkboxConfirmed"
          density="compact"
          hide-details
          class="mt-4"
        >
          <template #label>
            <span>{{ confirmCheckboxLabel }}</span>
          </template>
        </v-checkbox>
      </v-card-text>

      <v-divider />

      <div class="dlg-footer">
        <slot name="actions" :can-confirm="canConfirm" :loading="loading">
          <v-spacer />
          <v-btn
            variant="text"
            :disabled="loading"
            data-testid="dialog-cancel"
            @click="handleCancel"
          >
            {{ cancelText }}
          </v-btn>
          <v-btn
            :color="confirmButtonColor"
            variant="flat"
            :loading="loading"
            :disabled="!canConfirm"
            data-testid="dialog-confirm"
            @click="handleConfirm"
          >
            {{ confirmLabel }}
          </v-btn>
        </slot>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>

import { ref, computed, watch } from 'vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    required: true,
  },
  type: {
    type: String,
    default: 'info',
    validator: (val) => ['info', 'warning', 'danger', 'success', 'primary'].includes(val),
  },
  title: {
    type: String,
    required: true,
  },
  message: {
    type: String,
    default: '',
  },
  confirmLabel: {
    type: String,
    default: 'Confirm',
  },
  cancelText: {
    type: String,
    default: 'Cancel',
  },
  size: {
    type: [String, Number],
    default: 'md',
  },
  persistent: {
    type: Boolean,
    default: true,
  },
  scrollable: {
    type: Boolean,
    default: false,
  },
  loading: {
    type: Boolean,
    default: false,
  },
  confirmText: {
    type: String,
    default: '',
  },
  confirmCheckbox: {
    type: Boolean,
    default: false,
  },
  confirmCheckboxLabel: {
    type: String,
    default: 'I understand and want to proceed',
  },
  hideIcon: {
    type: Boolean,
    default: false,
  },
  icon: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel'])

const confirmInput = ref('')
const checkboxConfirmed = ref(false)

const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const maxWidth = computed(() => {
  const sizeMap = { sm: 400, md: 500, lg: 650, xl: 800 }
  return typeof props.size === 'number' ? props.size : sizeMap[props.size] || 500
})

const typeConfig = computed(() => {
  const configs = {
    info: {
      color: 'info',
      icon: 'mdi-information',
      headerVariant: '',
    },
    warning: {
      color: 'warning',
      icon: 'mdi-alert',
      headerVariant: 'dlg-header--warning',
    },
    danger: {
      color: 'error',
      icon: 'mdi-alert-circle',
      headerVariant: 'dlg-header--danger',
    },
    success: {
      color: 'success',
      icon: 'mdi-check-circle',
      headerVariant: '',
    },
    primary: {
      color: 'primary',
      icon: 'mdi-star-four-points',
      headerVariant: 'dlg-header--primary',
    },
  }
  return configs[props.type] || configs.info
})

const headerClasses = computed(() => {
  const classes = ['dlg-header']
  if (typeConfig.value.headerVariant) {
    classes.push(typeConfig.value.headerVariant)
  }
  return classes
})

const showIcon = computed(() => !props.hideIcon)
const iconName = computed(() => props.icon || typeConfig.value.icon)
const confirmButtonColor = computed(() => typeConfig.value.color)

const canConfirm = computed(() => {
  if (props.confirmText) {
    return confirmInput.value === props.confirmText
  }
  if (props.confirmCheckbox) {
    return checkboxConfirmed.value
  }
  return true
})

function handleConfirm() {
  if (canConfirm.value) {
    emit('confirm')
  }
}

function handleCancel() {
  if (!props.loading) {
    emit('cancel')
    isOpen.value = false
  }
}

function handleDialogChange(val) {
  if (!val && !props.loading) {
    emit('cancel')
  }
}

watch(() => props.modelValue, (newVal) => {
  if (!newVal) {
    confirmInput.value = ''
    checkboxConfirmed.value = false
  }
})
</script>

<style scoped>
.base-dialog-card {
  background-color: rgb(var(--v-theme-surface));
  opacity: 1;
}
</style>
