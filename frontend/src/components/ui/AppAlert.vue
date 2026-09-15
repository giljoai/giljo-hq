<template>
  <v-alert
    :type="type"
    :variant="variant"
    :closable="closable"
    :prominent="prominent"
    :density="density"
    :border="border"
    :color="color"
    v-bind="$attrs"
  >
    <slot />
  </v-alert>
</template>

<script setup lang="ts">

interface Props {
  type?: 'success' | 'info' | 'warning' | 'error'
  variant?: 'text' | 'flat' | 'elevated' | 'tonal' | 'outlined' | 'plain'
  closable?: boolean
  prominent?: boolean
  density?: 'default' | 'comfortable' | 'compact'
  border?: boolean | 'top' | 'bottom' | 'start' | 'end'
  color?: string
}

withDefaults(defineProps<Props>(), {
  type: 'info',
  variant: 'tonal',
  closable: false,
  prominent: false,
  density: 'default',
  border: false,
})
</script>

<style scoped>
/*
  No custom styles needed - rely on Vuetify's design system.
  If application-wide alert customization is needed, add it here.
*/
</style>
