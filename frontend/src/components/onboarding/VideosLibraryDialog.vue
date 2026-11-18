<template>
  <v-dialog
    :model-value="modelValue"
    max-width="560"
    aria-labelledby="videos-library-title"
    @update:model-value="(open) => !open && emit('close')"
  >
    <v-card v-if="modelValue" class="smooth-border" data-testid="videos-library">
      <div class="dlg-header">
        <v-icon class="dlg-icon" icon="mdi-play-circle-outline" />
        <span id="videos-library-title" class="dlg-title" data-testid="videos-library-title">Videos and animations</span>
        <v-btn
          icon
          variant="text"
          size="small"
          class="dlg-close"
          data-testid="videos-library-close"
          aria-label="Close"
          @click="emit('close')"
        >
          <v-icon icon="mdi-close" size="18" />
        </v-btn>
      </div>

      <ul class="library-list">
        <li v-for="video in GUIDE_VIDEOS" :key="video.id">
          <button
            type="button"
            class="library-row smooth-border"
            :data-testid="`library-video-${video.id}`"
            @click="play(video)"
          >
            <v-icon class="library-row-icon" icon="mdi-play-circle-outline" size="22" />
            <span class="library-row-title">{{ video.title }}</span>
            <span class="library-row-length">{{ lengthOf(video) }}</span>
          </button>
        </li>
        <li>
          <button
            type="button"
            class="library-row smooth-border"
            data-testid="library-tour"
            @click="openTour"
          >
            <v-icon class="library-row-icon" icon="mdi-book-open-variant" size="22" />
            <span class="library-row-title">How it works (animated tour)</span>
            <span class="library-row-length">Tour</span>
          </button>
        </li>
      </ul>
    </v-card>
  </v-dialog>

  <IntroVideoDialog :model-value="playerOpen" :video="active" @close="playerOpen = false" />
</template>

<script setup>
import { ref } from 'vue'

import IntroVideoDialog from './IntroVideoDialog.vue'
import { GUIDE_VIDEOS } from '@/content/onboarding/guide'

defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'open-tour'])

const playerOpen = ref(false)
const active = ref(GUIDE_VIDEOS[0])

function play(video) {
  active.value = video
  playerOpen.value = true
}

function openTour() {
  emit('open-tour')
  emit('close')
}

function lengthOf(video) {
  const total = Math.round(video.seconds)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}
</script>

<style scoped lang="scss">
.library-list {
  list-style: none;
  margin: 0;
  padding: 16px 20px 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.library-row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 12px 14px;
  border: none;
  border-radius: 12px;
  background: var(--color-bg-elevated, transparent);
  color: var(--text-primary);
  font-family: inherit;
  font-size: 0.95rem;
  text-align: left;
  cursor: pointer;
  transition: box-shadow 150ms ease-out;
}

.library-row:hover {
  --smooth-border-color: var(--color-accent-primary);
}

.library-row:focus-visible {
  outline: 2px solid var(--color-accent-primary);
  outline-offset: 2px;
}

.library-row-icon {
  color: var(--agent-orchestrator-primary);
}

.library-row-title {
  flex: 1;
  min-width: 0;
}

.library-row-length {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.8rem;
  color: var(--text-secondary);
}
</style>
