<template>
  <div v-if="visible" class="starfield" :style="{ opacity: starOpacity }" aria-hidden="true">
    <div ref="layerSmall" class="starfield-layer starfield-layer--small"></div>
    <div ref="layerMedium" class="starfield-layer starfield-layer--medium"></div>
    <div ref="layerLarge" class="starfield-layer starfield-layer--large"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const layerSmall = ref(null)
const layerMedium = ref(null)
const layerLarge = ref(null)

const visible = ref(true)
const starOpacity = ref(1)
let dayNightTimer = null

function updateDayNight() {
  const now = new Date()
  const h = now.getHours()
  const m = now.getMinutes()
  const t = h + m / 60

  if (t >= 6.5 && t < 18.5) {
    visible.value = false
    starOpacity.value = 0
  } else if (t >= 6 && t < 6.5) {
    visible.value = true
    starOpacity.value = 1 - (t - 6) / 0.5
  } else if (t >= 18.5 && t < 19) {
    visible.value = true
    starOpacity.value = (t - 18.5) / 0.5
  } else {
    visible.value = true
    starOpacity.value = 1
  }
}

const PARALLAX_SMALL = 0.02
const PARALLAX_MEDIUM = 0.05
const PARALLAX_LARGE = 0.10

let scrollY = 0
let targetY = 0
let rafId = null

function onWheel(e) {
  targetY = Math.max(0, Math.min(targetY + e.deltaY, 5000))
}

function animate() {
  scrollY += (targetY - scrollY) * 0.06

  if (layerSmall.value) {
    layerSmall.value.style.transform = `translate3d(0, ${-scrollY * PARALLAX_SMALL}px, 0)`
  }
  if (layerMedium.value) {
    layerMedium.value.style.transform = `translate3d(${scrollY * PARALLAX_MEDIUM * 0.3}px, ${-scrollY * PARALLAX_MEDIUM}px, 0)`
  }
  if (layerLarge.value) {
    layerLarge.value.style.transform = `translate3d(${-scrollY * PARALLAX_LARGE * 0.2}px, ${-scrollY * PARALLAX_LARGE}px, 0)`
  }

  rafId = requestAnimationFrame(animate)
}

onMounted(() => {
  updateDayNight()
  dayNightTimer = setInterval(updateDayNight, 60_000)
  window.addEventListener('wheel', onWheel, { passive: true })
  rafId = requestAnimationFrame(animate)
})

onUnmounted(() => {
  window.removeEventListener('wheel', onWheel)
  if (rafId) cancelAnimationFrame(rafId)
  if (dayNightTimer) clearInterval(dayNightTimer)
})
</script>

<style scoped lang="scss">
.starfield {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  overflow: hidden;
  transition: opacity 60s ease; // slow 1-min fade for dawn/dusk
}

.starfield-layer {
  position: absolute;
  inset: -40px; // bleed area so parallax doesn't reveal edges
  will-change: transform;
}

// Small stars: 1px
.starfield-layer--small {
  background-image:
    radial-gradient(1px 1px at 47px 82px, rgba(255,255,255,0.25), transparent),
    radial-gradient(1px 1px at 182px 341px, rgba(255,255,255,0.22), transparent),
    radial-gradient(1px 1px at 311px 97px, rgba(255,255,255,0.24), transparent),
    radial-gradient(1px 1px at 527px 212px, rgba(255,255,255,0.20), transparent),
    radial-gradient(1px 1px at 684px 471px, rgba(255,255,255,0.23), transparent),
    radial-gradient(1px 1px at 73px 518px, rgba(255,255,255,0.21), transparent),
    radial-gradient(1px 1px at 891px 133px, rgba(255,255,255,0.25), transparent),
    radial-gradient(1px 1px at 1023px 387px, rgba(255,255,255,0.22), transparent),
    radial-gradient(1px 1px at 412px 642px, rgba(255,255,255,0.20), transparent),
    radial-gradient(1px 1px at 157px 773px, rgba(255,255,255,0.24), transparent),
    radial-gradient(1px 1px at 763px 54px, rgba(255,255,255,0.21), transparent),
    radial-gradient(1px 1px at 1147px 298px, rgba(255,255,255,0.23), transparent),
    radial-gradient(1px 1px at 234px 167px, rgba(255,255,255,0.22), transparent),
    radial-gradient(1px 1px at 598px 731px, rgba(255,255,255,0.20), transparent),
    radial-gradient(1px 1px at 1291px 521px, rgba(255,255,255,0.25), transparent),
    radial-gradient(1px 1px at 842px 612px, rgba(255,255,255,0.21), transparent),
    radial-gradient(1px 1px at 1089px 89px, rgba(255,255,255,0.24), transparent),
    radial-gradient(1px 1px at 367px 438px, rgba(255,255,255,0.20), transparent),
    radial-gradient(1px 1px at 1432px 192px, rgba(255,255,255,0.22), transparent),
    radial-gradient(1px 1px at 956px 847px, rgba(255,255,255,0.23), transparent),
    radial-gradient(1px 1px at 123px 923px, rgba(255,255,255,0.21), transparent),
    radial-gradient(1px 1px at 1567px 437px, rgba(255,255,255,0.25), transparent),
    radial-gradient(1px 1px at 478px 1012px, rgba(255,255,255,0.20), transparent),
    radial-gradient(1px 1px at 1201px 678px, rgba(255,255,255,0.24), transparent);
  background-size: 1600px 1100px;
}

// Medium stars: 1.5-2px
.starfield-layer--medium {
  background-image:
    radial-gradient(1.5px 1.5px at 203px 147px, rgba(255,255,255,0.28), transparent),
    radial-gradient(2px 2px at 567px 312px, rgba(255,255,255,0.25), transparent),
    radial-gradient(1.5px 1.5px at 891px 523px, rgba(255,255,255,0.30), transparent),
    radial-gradient(2px 2px at 134px 687px, rgba(255,255,255,0.24), transparent),
    radial-gradient(1.5px 1.5px at 1078px 241px, rgba(255,255,255,0.27), transparent),
    radial-gradient(2px 2px at 423px 892px, rgba(255,255,255,0.29), transparent),
    radial-gradient(1.5px 1.5px at 756px 78px, rgba(255,255,255,0.26), transparent),
    radial-gradient(2px 2px at 1312px 456px, rgba(255,255,255,0.23), transparent),
    radial-gradient(1.5px 1.5px at 289px 534px, rgba(255,255,255,0.30), transparent),
    radial-gradient(2px 2px at 1456px 712px, rgba(255,255,255,0.25), transparent),
    radial-gradient(1.5px 1.5px at 645px 167px, rgba(255,255,255,0.28), transparent),
    radial-gradient(2px 2px at 1023px 834px, rgba(255,255,255,0.24), transparent);
  background-size: 1600px 1100px;
}

// Large stars: 3-4px, rare, with twinkle
.starfield-layer--large {
  background-image:
    radial-gradient(3px 3px at 312px 234px, rgba(255,255,255,0.20), transparent),
    radial-gradient(4px 4px at 867px 423px, rgba(255,255,255,0.16), transparent),
    radial-gradient(3px 3px at 1234px 167px, rgba(255,255,255,0.18), transparent),
    radial-gradient(3.5px 3.5px at 534px 712px, rgba(255,255,255,0.17), transparent),
    radial-gradient(4px 4px at 1089px 634px, rgba(255,255,255,0.15), transparent),
    radial-gradient(3px 3px at 178px 891px, rgba(255,255,255,0.19), transparent);
  background-size: 1600px 1100px;
  animation: starfield-twinkle 8s ease-in-out infinite alternate;
}

@keyframes starfield-twinkle {
  0% { opacity: 0.6; }
  50% { opacity: 1; }
  100% { opacity: 0.7; }
}
</style>
