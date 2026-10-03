<template>
  <div class="toast-manager">
    <v-snackbar
      v-for="(toast, index) in toasts"
      :key="toast.id"
      v-model="toast.show"
      :color="toast.color"
      :location="vuetifyLocation"
      :timeout="storeDuration"
      :min-height="toast.multiLine ? 68 : undefined"
      :style="{ marginBottom: `${index * 60}px` }"
      @update:model-value="(val) => !val && removeToast(index)"
    >
      <div class="d-flex align-center">
        <v-icon v-if="toast.icon" :icon="toast.icon" class="mr-3" />
        <div class="flex-grow-1">
          <div v-if="toast.title" class="font-weight-bold">{{ toast.title }}</div>
          <div>{{ toast.message }}</div>
        </div>
      </div>

      <template #actions>
        <v-btn v-if="toast.action" variant="text" @click="handleAction(toast)">
          {{ toast.action.label }}
        </v-btn>
        <v-btn
          icon="mdi-close"
          variant="text"
          aria-label="Close notification"
          @click="toast.show = false"
        />
      </template>
    </v-snackbar>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const MAX_TOASTS = 5

const toasts = ref([])
const toastId = ref(0)
const settingsStore = useSettingsStore()

const positionMap = {
  'top-left': 'top start',
  'top-center': 'top center',
  'top-right': 'top end',
  'bottom-left': 'bottom start',
  'bottom-center': 'bottom center',
  'bottom-right': 'bottom end',
}

const vuetifyLocation = computed(() => {
  const pos = settingsStore.notificationPosition
  return positionMap[pos] || 'bottom end'
})

const storeDuration = computed(() => settingsStore.notificationDuration)

const toastTypes = {
  success: {
    color: 'success',
    icon: 'mdi-check-circle',
  },
  error: {
    color: 'error',
    icon: 'mdi-alert-circle',
  },
  warning: {
    color: 'warning',
    icon: 'mdi-alert',
  },
  info: {
    color: 'info',
    icon: 'mdi-information',
  },
}

function showToast(options) {
  const typeConfig = toastTypes[options.type] || {}

  const toast = {
    id: ++toastId.value,
    show: true,
    message: options.message || '',
    title: options.title,
    type: options.type || 'info',
    color: options.color || typeConfig.color || 'grey',
    icon: options.icon !== false ? options.icon || typeConfig.icon : null,
    multiLine: options.multiLine || false,
    action: options.action,
  }

  if (toasts.value.length >= MAX_TOASTS) {
    toasts.value.shift()
  }

  toasts.value.push(toast)

  return toast.id
}

function removeToast(index) {
  toasts.value.splice(index, 1)
}

function clearToasts() {
  toasts.value = []
}

if (typeof window !== 'undefined') {
  window.$toast = {
    show: showToast,
    success: (message, options = {}) => showToast({ ...options, message, type: 'success' }),
    error: (message, options = {}) => showToast({ ...options, message, type: 'error' }),
    warning: (message, options = {}) => showToast({ ...options, message, type: 'warning' }),
    info: (message, options = {}) => showToast({ ...options, message, type: 'info' }),
    clear: clearToasts,
  }
}

function handleAction(toast) {
  if (toast.action && typeof toast.action.callback === 'function') {
    toast.action.callback()
  }
  toast.show = false
}

function handleToastEvent(event) {
  showToast(event.detail)
}

defineExpose({
  showToast,
  clearToasts,
})

onMounted(() => {
  window.addEventListener('show-toast', handleToastEvent)
})

onUnmounted(() => {
  window.removeEventListener('show-toast', handleToastEvent)
  delete window.$toast
})
</script>

<style lang="scss" scoped>
@use '@/styles/design-tokens' as *;
.toast-manager {
  z-index: 9999;
}

:deep(.v-snackbar__wrapper) {
  min-width: 300px;
  max-width: 500px;
}

/* Ensure toasts render above setup wizard overlay (z-index: 2100) */
:deep(.v-overlay__content) {
  z-index: 10000 !important;
}

/* Slide animation based on position */
.toast-enter-active,
.toast-leave-active {
  transition: all $transition-slow ease;
}

.toast-enter-from {
  transform: translateX(100%);
  opacity: 0;
}

.toast-leave-to {
  transform: translateX(100%);
  opacity: 0;
}

/* For left-positioned toasts */
.toast-manager[data-position*='left'] .toast-enter-from,
.toast-manager[data-position*='left'] .toast-leave-to {
  transform: translateX(-100%);
}

/* For top-positioned toasts */
.toast-manager[data-position^='top'] .toast-enter-from {
  transform: translateY(-100%);
}

.toast-manager[data-position^='top'] .toast-leave-to {
  transform: translateY(-100%);
}
</style>
