<template>
  <v-container fluid class="fill-height token-action-container">
    <v-row class="align-center justify-center">
      <v-col cols="12" sm="8" md="5" lg="4">
        <v-card elevation="8" class="token-action-card smooth-border">
          <v-card-title class="text-center pa-6">
            <div class="d-flex flex-column align-center w-100">
              <v-img
                src="/Giljo_YW.svg"
                :alt="productName"
                height="50"
                width="auto"
                max-width="200"
                class="mb-3"
              />
              <h1 class="text-headline-small font-weight-bold">{{ title }}</h1>
            </div>
          </v-card-title>

          <v-divider />

          <v-card-text class="pa-6">
            <slot v-if="loading" name="loading" />
            <slot v-else-if="tokenMissing" name="token-missing" />
            <slot v-else-if="success" name="success" />
            <slot v-else-if="prompt" name="prompt" />
            <slot v-else name="error" />
          </v-card-text>

          <v-divider />

          <v-card-text class="text-center pa-4">
            <a
              href="https://www.giljo.ai"
              target="_blank"
              rel="noopener noreferrer"
              class="text-body-small text-decoration-none"
              style="color: var(--text-muted);"
            >
              www.giljo.ai
            </a>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script setup>
import { PRODUCT_NAME } from '@/branding'

const productName = PRODUCT_NAME

defineProps({
  title: {
    type: String,
    required: true,
  },
  loading: {
    type: Boolean,
    default: false,
  },
  tokenMissing: {
    type: Boolean,
    default: false,
  },
  success: {
    type: Boolean,
    default: false,
  },
  prompt: {
    type: Boolean,
    default: false,
  },
})
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;

.token-action-container {
  background: linear-gradient(135deg, rgb(30, 49, 71) 0%, rgb(18, 29, 42) 100%);
  min-height: 100vh;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 9999;
  overflow-y: auto;
}

.token-action-card {
  border-radius: $border-radius-rounded;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}
</style>
