<template>
  <v-card variant="flat" class="smooth-border billing-card" data-test="billing-stub">
    <v-card-text class="pa-6 text-center">
      <v-icon size="48" color="primary" class="mb-3">mdi-cloud-outline</v-icon>
      <h2 class="text-title-large mb-2">Want GiljoAI as a managed service?</h2>
      <p class="text-body-medium text-muted-a11y mb-5">
        You're running the self-hosted edition — free to run and fully yours to control. Prefer
        not to manage the infrastructure? The managed service hosts {{ productName }} for you, with
        secure OAuth connections to Claude.ai online suite, Claude desktop, Chatgpt.com, and more.
        Try now for 7 days free, no local setup, no upkeep.
      </p>
      <v-btn
        color="primary"
        variant="flat"
        href="https://www.giljo.ai"
        target="_blank"
        rel="noopener noreferrer"
        data-test="managed-service-link"
      >
        Explore the managed service
        <v-icon end>mdi-arrow-top-right</v-icon>
      </v-btn>
    </v-card-text>
  </v-card>
</template>

<script setup>
// CE-only view. In CE there is no billing, so instead of a payment surface we
// invite self-hosted users to the managed service (hosted Giljo HQ with
// OAuth client integrations). The SaaS route override at
// `frontend/src/saas/routes/index.js` replaces this with the real subscription
// dashboard in SaaS mode, so this card never renders for hosted customers.
// Provider-neutral by design: no billing-provider names appear here (export gate).
import { PRODUCT_NAME } from '@/branding'

const productName = PRODUCT_NAME
</script>

<style lang="scss" scoped>
.billing-card {
  max-width: 640px;
  margin: 0 auto;
}
</style>
