<template>
  <div class="gil-mascot" :style="{ width: size + 'px', height: height + 'px', color: eyeColor }">
    <svg viewBox="0 0 250 250" xmlns="http://www.w3.org/2000/svg">
      <g id="Layer_1">
        <path
          class="st3"
          d="M226.87,73.06c-2.29-7.5-5.95-14.44-10.99-20.83-5.04-6.39-11.66-11.69-19.86-15.91-8.2-4.22-18.17-6.33-29.88-6.33h-82.44c-6.33,0-13.24,1.12-20.74,3.34-7.5,2.23-14.44,5.89-20.83,10.99-6.39,5.1-11.72,11.72-16,19.86-4.28,8.15-6.42,18.08-6.42,29.79v61.88c0,11.84,2.14,21.83,6.42,29.97,4.28,8.15,9.61,14.77,16,19.86,6.39,5.1,13.33,8.76,20.83,10.99,7.5,2.23,14.41,3.34,20.74,3.34h82.44c4.33,0,8.93-.5,13.8-1.49,4.86-.99,9.67-2.55,14.41-4.66s9.29-4.83,13.62-8.17c4.33-3.34,8.14-7.38,11.43-12.13,3.28-4.75,5.92-10.25,7.91-16.52,1.99-6.27,2.99-13.33,2.99-21.18v-61.88c0-6.44-1.14-13.42-3.43-20.92ZM184.59,155.85c0,5.98-1.52,10.55-4.57,13.71-3.05,3.16-7.68,4.75-13.89,4.75h-82.09c-6.09,0-10.72-1.58-13.89-4.75s-4.75-7.73-4.75-13.71v-61.88c0-5.98,1.58-10.52,4.75-13.62,3.16-3.1,7.79-4.66,13.89-4.66h82.09c5.98,0,10.55,1.52,13.71,4.57,3.16,3.05,4.75,7.73,4.75,14.06v61.52Z"
        />

        <g v-show="eyeState === 'open'" id="eyes-open">
          <circle class="st1" :cx="93.87" :cy="148.51" r="19.5" />
          <circle class="st1" :cx="138.37" :cy="148.51" r="19.5" />
        </g>

        <g v-show="eyeState === 'closed'" id="eyes-closed">
          <rect class="st1" x="74.37" y="145.81" width="39" height="5.4" />
          <rect class="st1" x="118.87" y="145.81" width="39" height="5.4" />
        </g>

        <g v-show="eyeState === 'happy'" id="eyes-happy">
          <path class="st-happy" d="M74.37,152.51 A19.5,15 0 0,1 113.37,152.51" />
          <path class="st-happy" d="M118.87,152.51 A19.5,15 0 0,1 157.87,152.51" />
        </g>
      </g>
    </svg>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'

const props = defineProps({
  size: { type: Number, default: 150 },
  darkEyes: { type: Boolean, default: false },
  happy: { type: Boolean, default: false },
})

const height = computed(() => Math.round(props.size * 1.13))

const eyeState = ref('open')
let blinkTimeout = null

function doBlink(onDone) {
  if (eyeState.value === 'happy') { onDone(); return }
  eyeState.value = 'closed'
  setTimeout(() => {
    if (eyeState.value === 'closed') eyeState.value = 'open'
    onDone()
  }, 120 + Math.random() * 80)
}

function scheduleNextBlink() {
  const roll = Math.random()
  let delay

  if (roll < 0.25) {
    delay = 1500 + Math.random() * 2000
    blinkTimeout = setTimeout(() => {
      doBlink(() => {
        setTimeout(() => {
          doBlink(() => scheduleNextBlink())
        }, 180 + Math.random() * 120)
      })
    }, delay)
  } else {
    delay = 1500 + Math.random() * 3000
    blinkTimeout = setTimeout(() => {
      doBlink(() => scheduleNextBlink())
    }, delay)
  }
}

watch(() => props.happy, (isHappy) => {
  if (isHappy) {
    eyeState.value = 'happy'
  } else {
    eyeState.value = 'open'
  }
})

onMounted(() => {
  scheduleNextBlink()
})

onUnmounted(() => {
  if (blinkTimeout) clearTimeout(blinkTimeout)
})

const eyeColor = computed(() => (props.darkEyes ? 'rgb(var(--v-theme-background))' : 'rgb(var(--v-theme-on-surface))'))
</script>

<style scoped>
.gil-mascot {
  background: transparent;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
svg {
  display: block;
  background: transparent;
}

/* SVG class styles */
.st0 {
  fill: transparent;
}
.st1 {
  fill: currentColor;
}
.st2 {
  fill: none;
}
.st3 {
  fill: rgb(var(--v-theme-primary));
}
.st-happy {
  fill: none;
  stroke: currentColor;
  stroke-width: 5;
  stroke-linecap: round;
}
</style>
