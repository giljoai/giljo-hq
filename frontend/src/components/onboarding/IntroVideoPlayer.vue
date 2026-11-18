<template>
  <video
    ref="videoEl"
    class="intro-video-player"
    data-testid="intro-video-player"
    :src="video.video"
    controls
    playsinline
    preload="metadata"
    crossorigin="anonymous"
    @play="arm"
    @loadedmetadata="onLoaded"
    @waiting="arm"
    @playing="disarm"
    @timeupdate="disarm"
    @pause="disarm"
    @ended="onEnded"
    @error="onError"
  >
    <track kind="captions" srclang="en" label="English" default :src="video.captions" />
  </video>
</template>

<script setup>
import { onBeforeUnmount, ref } from 'vue'

import { INTRO_VIDEO_STALL_MS } from '@/composables/useIntroVideo'

defineProps({
  video: { type: Object, required: true },
})
const emit = defineEmits(['ended', 'error', 'stalled'])

const videoEl = ref(null)
let timer = null
let finished = false

function disarm() {
  if (timer) clearTimeout(timer)
  timer = null
}

function arm() {
  if (finished) return
  disarm()
  timer = setTimeout(() => {
    timer = null
    finished = true
    emit('stalled')
  }, INTRO_VIDEO_STALL_MS)
}

function onLoaded() {
  disarm()
}

function onEnded() {
  finished = true
  disarm()
  emit('ended')
}

function onError() {
  finished = true
  disarm()
  emit('error')
}

onBeforeUnmount(disarm)

defineExpose({ videoEl })
</script>

<style scoped lang="scss">
.intro-video-player {
  display: block;
  width: 100%;
  max-height: 60vh;
  background: var(--color-bg-primary);
  border-radius: 8px;
}
</style>
