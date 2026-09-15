<template>
  <v-container fluid class="fill-height pa-0">
    <v-row class="align-center justify-center fill-height">
      <v-col cols="12" sm="8" md="6" lg="4">
        <v-card class="mx-auto smooth-border notfound-card" elevation="8">
          <div class="notfound-body">
            <img src="/icons/Giljo_YW_Face.svg" alt="" class="notfound-face" />
            <div class="notfound-code">404</div>
            <h1 class="text-headline-large notfound-title">Page not found</h1>
            <p class="text-body-large notfound-sub">
              We couldn't find the page you were looking for. It may have moved, or
              the link may be out of date.
            </p>

            <div class="notfound-actions">
              <v-btn
                color="primary"
                size="large"
                prepend-icon="mdi-home"
                data-testid="notfound-home"
                @click="goHome"
              >
                Go to Home
              </v-btn>
              <v-btn
                variant="text"
                size="large"
                prepend-icon="mdi-arrow-left"
                data-testid="notfound-back"
                @click="goBack"
              >
                Go back
              </v-btn>
            </div>
          </div>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()

function goHome() {
  router.push('/')
}

function goBack() {
  if (typeof window !== 'undefined' && window.history.length > 1) {
    router.back()
  } else {
    router.push('/')
  }
}
</script>

<style scoped lang="scss">
@use '../styles/design-tokens' as *;

.fill-height {
  min-height: 100vh;
}

.notfound-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 48px 32px;
  gap: 12px;
}

.notfound-face {
  width: 64px;
  height: 64px;
  margin-bottom: 4px;
}

.notfound-code {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 700;
  font-size: 56px;
  line-height: 1;
  letter-spacing: -0.02em;
  color: $color-brand-yellow;
}

.notfound-title {
  margin: 0;
  color: $color-text-primary;
}

.notfound-sub {
  margin: 0 0 8px;
  max-width: 36ch;
  color: var(--text-secondary);
}

.notfound-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  justify-content: center;
  margin-top: 8px;
}
</style>
