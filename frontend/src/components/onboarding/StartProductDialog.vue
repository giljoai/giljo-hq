<template>
  <v-dialog
    :model-value="modelValue"
    max-width="880"
    :fullscreen="isPhone"
    scrollable
    aria-labelledby="start-product-title"
    @update:model-value="onDialogModel"
  >
    <v-card v-if="modelValue" class="smooth-border" data-testid="start-product-dialog">
      <div class="dlg-header">
        <v-icon class="dlg-icon" icon="mdi-package-variant-closed" />
        <span id="start-product-title" class="dlg-title">Add your product</span>
        <v-btn
          icon
          variant="text"
          size="small"
          class="dlg-close"
          data-testid="start-product-close"
          aria-label="Close"
          @click="close"
        >
          <v-icon icon="mdi-close" size="18" />
        </v-btn>
      </div>

      <div class="spd-body">
        <TutorialRouter v-if="s.screen === 'beats'" @pick="onPick" />
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
          @activated="onActivated"
        />
      </div>

      <div v-if="showBack" class="dlg-footer">
        <v-btn variant="text" data-testid="start-product-back" @click="back">Back</v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import TutorialRouter from '@/components/tutorial/TutorialRouter.vue'
import TutorialPromptScreen from '@/components/tutorial/TutorialPromptScreen.vue'
import TutorialUploadScreen from '@/components/tutorial/TutorialUploadScreen.vue'
import TutorialReviewScreen from '@/components/tutorial/TutorialReviewScreen.vue'
import { armActivateBreadcrumb, useTutorialState } from '@/composables/useTutorialState'
import { useProductStore } from '@/stores/products'

const PHONE_WIDTH = 600
const BLANK_PRODUCT_FORM = '/Products?create=blank'
const DOORS_STOP = 6

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const router = useRouter()
const productStore = useProductStore()
const {
  s,
  back,
  openAt,
  pick,
  setProduct,
  goToUpload,
  goToReview,
  finishToDone,
  releaseAbandonedDraft,
} = useTutorialState()

const isPhone = ref(window.innerWidth < PHONE_WIDTH)
const showBack = computed(() => s.screen === 'prompt' || s.screen === 'upload')

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    isPhone.value = window.innerWidth < PHONE_WIDTH
    openAt(DOORS_STOP)
  },
  { immediate: true },
)

function leave() {
  emit('update:modelValue', false)
}

async function close() {
  await releaseAbandonedDraft()
  leave()
}

function onDialogModel(open) {
  if (!open) close()
}

function onPick(path) {
  if (path === 'C') {
    armActivateBreadcrumb()
    leave()
    router.push(BLANK_PRODUCT_FORM)
    return
  }
  pick(path)
}

let leavingForManual = false
async function goManual() {
  if (leavingForManual) return
  leavingForManual = true
  try {
    await releaseAbandonedDraft()
    armActivateBreadcrumb()
    leave()
    router.push(s.productId ? `/Products?edit=${encodeURIComponent(s.productId)}` : BLANK_PRODUCT_FORM)
  } finally {
    leavingForManual = false
  }
}

function onActivated() {
  const productId = s.productId
  finishToDone()
  leave()
  if (!productId) return
  productStore.openTab(productId).catch((error) => {
    console.warn('[StartProductDialog] could not select the product it created:', error)
  })
}
</script>

<style scoped lang="scss">
.spd-body {
  padding: 24px 28px 20px;
  overflow-y: auto;
  min-height: 0;
}

@media (max-width: 599px) {
  .spd-body {
    padding: 16px 16px 12px;
  }
}
</style>
