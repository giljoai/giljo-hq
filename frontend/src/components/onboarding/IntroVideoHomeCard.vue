<template>
  <div v-if="visible" class="intro-video-card smooth-border" data-testid="intro-video-home-card">
    <button
      type="button"
      class="intro-video-card__open"
      data-testid="intro-video-home-card-open"
      @click="open = true"
    >
      <v-icon icon="mdi-play-circle-outline" size="20" class="intro-video-card__icon" />
      <span class="intro-video-card__label">Watch: {{ video.title }} ({{ length }})</span>
    </button>
    <button
      type="button"
      class="intro-video-card__dismiss"
      data-testid="intro-video-home-card-dismiss"
      aria-label="Hide this video link"
      @click="hide"
    >
      <v-icon icon="mdi-close" size="16" />
    </button>
    <IntroVideoDialog :model-value="open" :video="video" @close="open = false" />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

import IntroVideoDialog from './IntroVideoDialog.vue'
import { ONBOARDING_INTRO_VIDEO } from '@/content/onboarding/videos'
import { isFirstThirtyDays } from '@/composables/useIntroVideo'
import { useBannerDismissStore } from '@/stores/bannerDismissStore'
import { useUserStore } from '@/stores/user'

const HIDDEN_KEY = 'intro-video:home-card'

const video = ONBOARDING_INTRO_VIDEO
const userStore = useUserStore()
const dismissals = useBannerDismissStore()
const open = ref(false)

const length = computed(() => {
  const total = Math.round(video.seconds)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
})

const visible = computed(
  () => isFirstThirtyDays(userStore.currentUser?.created_at) && !dismissals.isDismissed(HIDDEN_KEY),
)

function hide() {
  dismissals.dismiss(HIDDEN_KEY)
}
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens' as *;

.intro-video-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: 12px 0;
  padding: 6px 8px 6px 14px;
  border-radius: $border-radius-rounded;
  background: rgb(var(--v-theme-surface));
}

.intro-video-card__open {
  display: flex;
  align-items: center;
  flex: 1;
  gap: 10px;
  padding: 6px 0;
  background: none;
  border: 0;
  color: var(--text-secondary);
  cursor: pointer;
  text-align: left;
  font-family: 'Roboto', sans-serif;
  font-size: 0.9rem;
}

.intro-video-card__open:hover,
.intro-video-card__open:focus-visible {
  color: rgb(var(--v-theme-on-surface));
}

.intro-video-card__icon {
  color: var(--color-accent-primary);
}

.intro-video-card__dismiss {
  background: none;
  border: 0;
  padding: 6px;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 8px;
}

.intro-video-card__dismiss:hover,
.intro-video-card__dismiss:focus-visible {
  color: rgb(var(--v-theme-on-surface));
}
</style>
