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
/* Page roots are fixed scroll containers; stop them at the fixed KYB footer's
   top edge (42px tall) so no content scrolls underneath it. */
.v-application__wrap:has(> .kyb-footer) > .v-main > :deep(*) {
  bottom: 42px;
  height: auto;
  min-height: 0;
}
</style>
