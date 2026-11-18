<template>
  <v-dialog
    :model-value="modelValue"
    persistent
    max-width="800"
    aria-labelledby="intro-video-title"
    @keydown="onKeydown"
    @click:outside="requestClose"
  >
    <v-card v-if="modelValue" class="smooth-border" data-testid="intro-video-dialog">
      <div class="dlg-header">
        <v-icon class="dlg-icon" icon="mdi-play-circle-outline" />
        <span id="intro-video-title" class="dlg-title">{{ title }}</span>
        <v-btn
          icon
          variant="text"
          size="small"
          class="dlg-close"
          data-testid="intro-video-close"
          aria-label="Close"
          :aria-disabled="canClose ? 'false' : 'true'"
          @click="requestClose"
        >
          <v-icon icon="mdi-close" size="18" />
        </v-btn>
      </div>

      <div class="intro-video-body">
        <p v-if="gated" class="intro-video-line">Watch this first. It takes under two minutes.</p>
        <IntroVideoPlayer
          :video="video"
          @ended="ended = true"
          @error="failed = true"
          @stalled="failed = true"
        />
        <p v-if="failed" class="intro-video-failure" role="alert" data-testid="intro-video-failure">
          The video could not play. You can watch it later in Tools, Learning.
        </p>
        <p
          v-if="failed && video.transcript"
          class="intro-video-transcript"
          data-testid="intro-video-transcript"
        >
          {{ video.transcript }}
        </p>
      </div>

      <div v-if="gated" class="dlg-footer">
        <span
          v-if="!canClose"
          id="intro-video-hint"
          class="intro-video-hint"
          data-testid="intro-video-hint"
          >Watch the video to continue</span
        >
        <v-spacer />
        <v-btn
          color="primary"
          variant="flat"
          data-testid="intro-video-continue"
          :disabled="!canClose"
          aria-describedby="intro-video-hint"
          @click="requestClose"
        >
          Continue
        </v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

import IntroVideoPlayer from './IntroVideoPlayer.vue'
import { ONBOARDING_INTRO_VIDEO } from '@/content/onboarding/videos'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  gated: { type: Boolean, default: false },
  video: { type: Object, default: () => ONBOARDING_INTRO_VIDEO },
})
const emit = defineEmits(['close'])

const ended = ref(false)
const failed = ref(false)

const canClose = computed(() => !props.gated || ended.value || failed.value)
const title = computed(() => (props.gated ? 'Welcome to Giljo HQ' : props.video.title))

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      ended.value = false
      failed.value = false
    }
  },
)

function requestClose() {
  if (canClose.value) emit('close')
}

function onKeydown(event) {
  if (event?.key === 'Escape') requestClose()
}
</script>

<style scoped lang="scss">
.intro-video-body {
  padding: 0 20px 16px;
}

.intro-video-line {
  margin: 0 0 12px;
  color: var(--text-secondary);
}

.intro-video-failure {
  margin: 12px 0 0;
  color: var(--text-secondary);
}

.intro-video-transcript {
  margin: 12px 0 0;
  max-height: 30vh;
  overflow-y: auto;
  white-space: pre-line;
  color: var(--text-secondary);
}

.intro-video-hint {
  color: var(--text-secondary);
  font-size: 0.85rem;
}
</style>
