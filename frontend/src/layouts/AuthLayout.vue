<template>
  <v-app>
    <v-main>
      <router-view />
    </v-main>
    <component :is="kybFooterComponent" v-if="kybFooterComponent" />
  </v-app>
</template>

<script setup>
import { shallowRef, onMounted } from 'vue'

const kybFooterComponent = shallowRef(null)

const kybFooterLoaders = import.meta.glob('@/saas/components/KybFooter.vue')
const [kybFooterLoader] = Object.values(kybFooterLoaders)

onMounted(async () => {
  if (!kybFooterLoader) return
  try {
    const mod = await kybFooterLoader()
    kybFooterComponent.value = mod.default
  } catch {
    // Non-fatal: footer fails to load silently. Login flow continues.
  }
})
</script>

<style scoped>
/* Minimal styling - authentication pages handle their own layout */
</style>
