<template>
  <div class="toast-manager">
    <v-snackbar
      v-for="(toast, index) in toasts"
      :key="toast.id"
      v-model="toast.show"
      :color="toast.color"
      :location="vuetifyLocation"
      :timeout="toast.timeout !== undefined ? toast.timeout : storeDuration"
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

// State
const toasts = ref([])
const toastId = ref(0)
const settingsStore = useSettingsStore()

// Map user-facing position values to Vuetify location strings
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

// Toast types configuration
// Timeout policy: success/info/warning fall through to the user's
// configured duration (Settings → Notifications). Errors stay sticky.
const toastTypes = {
  success: {
    color: 'success',
    icon: 'mdi-check-circle',
  },
  error: {
    color: 'error',
    icon: 'mdi-alert-circle',
    timeout: 0,
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

// Methods
function showToast(options) {
  // Get type configuration
  const typeConfig = toastTypes[options.type] || {}

  // Create toast object
  const toast = {
    id: ++toastId.value,
    show: true,
    message: options.message || '',
    title: options.title,
    type: options.type || 'info',
    color: options.color || typeConfig.color || 'grey',
    icon: options.icon !== false ? options.icon || typeConfig.icon : null,
    timeout: options.timeout !== undefined ? options.timeout : typeConfig.timeout,
    multiLine: options.multiLine || false,
    action: options.action,
  }

  // Limit number of toasts
  if (toasts.value.length >= MAX_TOASTS) {
    toasts.value.shift()
  }

  toasts.value.push(toast)

  // Auto-remove after timeout if specified
  if (toast.timeout > 0) {
    setTimeout(() => {
      const index = toasts.value.findIndex((t) => t.id === toast.id)
      if (index !== -1) {
        toasts.value[index].show = false
      }
    }, toast.timeout)
  }

  return toast.id
}

function removeToast(index) {
  toasts.value.splice(index, 1)
}

function clearToasts() {
  toasts.value = []
}

// Register global toast immediately after functions are defined
// This prevents race conditions where showToast is called before onMounted runs
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

// Event handlers for global toast events
function handleToastEvent(event) {
  showToast(event.detail)
}

// Expose methods for external use
defineExpose({
  showToast,
  clearToasts,
})

// Lifecycle
onMounted(() => {
  // Listen for global toast events (fallback for event-based dispatching)
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
