<template>
  <div class="consent-app">
    <div class="consent-app-name-row">
      <span class="consent-app-name" data-testid="consent-client-name">{{ client.name }}</span>
      <span
        v-if="client.redirectIsLocal"
        class="consent-mark consent-mark--local"
        data-testid="consent-local-mark"
      >
        <v-icon size="14" aria-hidden="true">mdi-laptop</v-icon>
        App on this computer
      </span>
      <span
        v-else-if="client.verified"
        class="consent-mark consent-mark--known"
        data-testid="consent-known-mark"
      >
        <v-icon size="14" aria-hidden="true">mdi-check-decagram-outline</v-icon>
        Known app site
      </span>
      <span
        v-else
        class="consent-mark consent-mark--unverified"
        data-testid="consent-unverified-mark"
      >
        <v-icon size="14" aria-hidden="true">mdi-alert-outline</v-icon>
        Unverified app
      </span>
    </div>
    <p class="consent-app-line">wants to access your {{ target }}</p>

    <dl class="consent-facts">
      <div class="consent-fact" data-testid="consent-redirect-host">
        <dt>Access goes to</dt>
        <dd>{{ destination }}</dd>
      </div>
      <div v-if="showPublisher" class="consent-fact" data-testid="consent-client-host">
        <dt>Published by</dt>
        <dd>{{ client.clientIdHost }}</dd>
      </div>
    </dl>

    <p
      v-if="showCaution"
      class="consent-caution smooth-border"
      role="note"
      data-testid="consent-unverified-caution"
    >
      {{ PRODUCT_NAME }} has not checked this app. Anyone can register an app under any name. Allow only if you
      trust {{ destination }}.
    </p>

    <p class="consent-started" data-testid="consent-started-yourself">
      Only allow this if you just started connecting this app yourself. If someone sent you this link, close this
      page.
    </p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { PRODUCT_NAME } from '@/branding'

const props = defineProps({
  client: {
    type: Object,
    required: true,
  },
  target: {
    type: String,
    default: 'account',
  },
})

const LOCAL_DESTINATION = 'an app on this computer'

const destination = computed(() =>
  props.client.redirectIsLocal ? LOCAL_DESTINATION : props.client.redirectHost || 'an unknown address',
)

const showPublisher = computed(
  () => Boolean(props.client.clientIdHost) && props.client.clientIdHost !== props.client.redirectHost,
)

const showCaution = computed(() => !props.client.redirectIsLocal && !props.client.verified)
</script>

<style lang="scss" scoped>
@use '@/styles/design-tokens' as *;

.consent-app-name-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.consent-app-name {
  font-size: 1rem;
  font-weight: 600;
  color: $color-text-primary;
  overflow-wrap: anywhere;
}

.consent-mark {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 8px;
  font-size: 0.75rem;
  font-weight: 600;
}

.consent-mark--known {
  background: rgba($color-status-complete, 0.15);
  color: $color-status-complete;
}

.consent-mark--local {
  background: rgba($color-text-secondary, 0.15);
  color: $color-text-secondary;
}

.consent-mark--unverified {
  background: rgba($color-status-warning, 0.15);
  color: $color-status-warning;
}

.consent-app-line {
  margin: 2px 0 0;
  font-size: 0.85rem;
  color: var(--text-muted);
}

.consent-facts {
  margin: 12px 0 0;
}

.consent-fact {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 0.85rem;

  dt {
    color: var(--text-secondary);
  }

  dd {
    margin: 0;
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 600;
    color: $color-text-primary;
    overflow-wrap: anywhere;
  }
}

.consent-started {
  margin: 12px 0 0;
  font-size: 0.82rem;
  line-height: 1.4;
  color: var(--text-secondary);
}

.consent-caution {
  --smooth-border-color: #{rgba($color-status-warning, 0.35)};
  margin: 12px 0 0;
  padding: 10px 12px;
  border-radius: $border-radius-default;
  background: rgba($color-status-warning, 0.08);
  font-size: 0.82rem;
  line-height: 1.4;
  color: $color-text-primary;
}
</style>
