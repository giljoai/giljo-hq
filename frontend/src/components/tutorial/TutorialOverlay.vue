<template>
  <Teleport to="body">
    <Transition name="overlay-fade">
      <div
        v-if="modelValue"
        class="tutorial-overlay"
        data-testid="tutorial-overlay"
        role="dialog"
        aria-modal="true"
        aria-label="GiljoAI tour"
        @keydown.escape="handleSkip"
      >
        <div class="tutorial-backdrop" />

        <div
          :class="['tutorial-panel', 'smooth-border', { 'tutorial--reduced': reducedMotion }]"
          tabindex="-1"
        >
          <TutorialRail :active-stop="railStop" @go="goTo" />

          <div class="tutorial-main">
            <div class="tutorial-content">
              <template v-if="s.screen === 'beats'">
                <TutorialBeat1 v-if="s.beat === 1" :key="`beat1-${replayKey}`" />
                <TutorialBeat2 v-else-if="s.beat === 2" :key="`beat2-${replayKey}`" />
                <TutorialBeat3 v-else-if="s.beat === 3" :key="`beat3-${replayKey}`" />
                <TutorialBeat4 v-else-if="s.beat === 4" :key="`beat4-${replayKey}`" />
                <TutorialBeat5 v-else-if="s.beat === 5" :key="`beat5-${replayKey}`" />
                <TutorialRouter v-else @pick="onPick" />
              </template>
              <TutorialPromptScreen
                v-else-if="s.screen === 'prompt'"
                :path="s.path || 'D'"
                :product-id="s.productId"
                @product-created="setProduct"
                @review="goToReview"
                @upload="goToUpload"
                @manual="goManual"
              />
              <TutorialUploadScreen
                v-else-if="s.screen === 'upload'"
                :product-id="s.productId"
                @product-created="setProduct"
                @product-invalidated="setProduct(null)"
                @review="goToReview"
                @manual="goManual"
              />
              <TutorialReviewScreen
                v-else-if="s.screen === 'review'"
                :product-id="s.productId"
                @activated="finishToDone"
              />
              <TutorialDoneScreen
                v-else-if="s.screen === 'done'"
                :router-choice="s.path"
                @close="handleSkip"
              />
            </div>

            <TutorialFooter
              :show-back="showBack"
              :show-next="showNext"
              :show-replay="s.screen === 'beats' && s.beat < 6"
              :next-label="nextLabel"
              @skip="handleSkip"
              @back="back"
              @next="next"
              @replay="replayKey++"
            />
          </div>
        </div>

        <BaseDialog
          v-model="showDoorCConfirm"
          type="warning"
          title="Leave the tutorial?"
          icon="mdi-pencil-outline"
          confirm-label="Open the product form"
          @confirm="confirmDoorC"
          @cancel="cancelDoorC"
        >
          <p data-testid="tutorial-doorc-confirm-text" class="mb-0">
            This opens the product form and leaves the tutorial — ready to fill it in yourself?
          </p>
        </BaseDialog>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import TutorialRail from './TutorialRail.vue'
import TutorialFooter from './TutorialFooter.vue'
import TutorialBeat1 from './beats/TutorialBeat1.vue'
import TutorialBeat2 from './beats/TutorialBeat2.vue'
import TutorialBeat3 from './beats/TutorialBeat3.vue'
import TutorialBeat4 from './beats/TutorialBeat4.vue'
import TutorialBeat5 from './beats/TutorialBeat5.vue'
import TutorialRouter from './TutorialRouter.vue'
import TutorialPromptScreen from './TutorialPromptScreen.vue'
import TutorialUploadScreen from './TutorialUploadScreen.vue'
import TutorialReviewScreen from './TutorialReviewScreen.vue'
import TutorialDoneScreen from './TutorialDoneScreen.vue'
import BaseDialog from '@/components/common/BaseDialog.vue'
import { armActivateBreadcrumb, useTutorialState } from '@/composables/useTutorialState'

defineProps({
  modelValue: {
    type: Boolean,
    required: true,
  },
})

const emit = defineEmits(['update:modelValue', 'dismiss'])

const router = useRouter()

const {
  s,
  railStop,
  showBack,
  showNext,
  nextLabel,
  next,
  back,
  goTo,
  pick,
  setProduct,
  goToUpload,
  goToReview,
  finishToDone,
  markComplete,
  releaseAbandonedDraft,
} = useTutorialState()

const replayKey = ref(0)

const reducedMotion = ref(
  typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches,
)

function close() {
  releaseAbandonedDraft()
  emit('dismiss')
  emit('update:modelValue', false)
}

function handleSkip() {
  markComplete()
  close()
}

const showDoorCConfirm = ref(false)

function onPick(path) {
  if (path === 'C') {
    showDoorCConfirm.value = true
    return
  }
  pick(path)
}

function cancelDoorC() {
  showDoorCConfirm.value = false
}

function leaveForManualForm() {
  armActivateBreadcrumb()
  markComplete()
  close()
  router.push('/Products?create=true')
}

function confirmDoorC() {
  showDoorCConfirm.value = false
  pick('C')
  leaveForManualForm()
}

function goManual() {
  leaveForManualForm()
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.overlay-fade-enter-active {
  transition: opacity 250ms ease-out;
}

.overlay-fade-leave-active {
  transition: opacity 200ms ease-in;
}

.overlay-fade-enter-from,
.overlay-fade-leave-to {
  opacity: 0;
}

.tutorial-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.tutorial-backdrop {
  position: absolute;
  inset: 0;
  background: rgba($color-background-primary, 0.85);
}

.tutorial-panel {
  position: relative;
  width: min(1080px, 96vw);
  height: min(660px, calc(100vh - 48px));
  background: $color-background-primary;
  border-radius: $border-radius-rounded;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1), 0 32px 96px rgba(0, 0, 0, 0.6);
  display: flex;
  overflow: hidden;
}

.tutorial-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.tutorial-content {
  flex: 1;
  padding: 34px 44px 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow-y: auto;
}

/* Per-beat "read more" deep link into /guide (proposal §3) — shared style,
   the beats themselves stay animation-only. */
.tutorial-content :deep(.beat-readmore) {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  color: $color-brand-yellow;
  text-decoration: none;
  white-space: nowrap;
  margin-left: 6px;

  &:hover {
    text-decoration: underline;
    text-underline-offset: 2px;
  }
}

/* Reduced motion — final frames instead of animation, both via the user's
   OS preference and via the class-driven gate above. */
@media (prefers-reduced-motion: reduce) {
  .tutorial-panel :deep(*) {
    animation: none !important;
  }
}

.tutorial--reduced :deep(*) {
  animation: none !important;
}
</style>
