<template>
  <component :is="layout">
    <router-view />
  </component>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AuthLayout from '@/layouts/AuthLayout.vue'
import DefaultLayout from '@/layouts/DefaultLayout.vue'

const route = useRoute()

const layout = computed(() => {
  if (!route.name) return AuthLayout
  return route.meta.layout === 'auth' ? AuthLayout : DefaultLayout
})
</script>

<style lang="scss">
@use '@/styles/design-tokens' as *;
/* Global styles */
html,
body {
  margin: 0;
  padding: 0;
  overflow-x: hidden;
}

html {
  /* Disable transitions during theme initialization */
  transition:
    background-color 0.3s,
    color 0.3s;
}

html.no-transition,
html.no-transition * {
  transition: none !important;
}

/* Theme-aware CSS variables */
[data-theme='dark'] {
  color-scheme: dark;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity $transition-normal ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Global toggle switch styling - green when ON, faded blue when OFF */
/* Applied throughout the entire application for consistency */
.v-switch .v-switch__thumb {
  background-color: rgba(33, 150, 243, 0.4) !important; /* Faded blue when OFF */
}

.v-switch .v-switch__track {
  background-color: rgba(33, 150, 243, 0.2) !important; /* Faded blue track when OFF */
}

.v-switch .v-selection-control--dirty .v-switch__thumb {
  background-color: rgb(var(--v-theme-success)) !important; /* Green when ON */
}

.v-switch .v-selection-control--dirty .v-switch__track {
  background-color: rgba(76, 175, 80, 0.3) !important; /* Green track when ON */
}
</style>
