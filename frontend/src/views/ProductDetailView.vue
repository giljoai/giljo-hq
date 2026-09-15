<template>
  <v-container fluid data-testid="product-detail-view">
    <v-row>
      <v-col cols="12">
        <v-btn icon variant="text" class="mb-4" @click="$router.back()">
          <v-icon>mdi-arrow-left</v-icon>
        </v-btn>

        <h1 class="text-headline-large mb-4">{{ product?.name || 'Product Details' }}</h1>

        <v-card v-if="loading">
          <v-card-text class="text-center py-8">
            <v-progress-circular indeterminate color="primary"></v-progress-circular>
          </v-card-text>
        </v-card>

        <v-card v-else-if="product" class="smooth-border product-detail-card">
          <v-card-text>
            <v-row>
              <v-col cols="12" md="6">
                <div class="text-title-small text-muted-a11y">Product ID</div>
                <div class="text-body-large font-monospace text-secondary-a11y" style="font-size: 0.75rem">{{ product.id }}</div>
              </v-col>
              <v-col cols="12" md="6">
                <div class="text-title-small text-muted-a11y">Created</div>
                <div class="text-body-large">{{ formatDateTime(product.created_at) }}</div>
              </v-col>
              <v-col cols="12">
                <div class="text-title-small text-muted-a11y">Description</div>
                <div class="text-body-large">{{ product.description || 'No description' }}</div>
              </v-col>
            </v-row>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useProductStore } from '@/stores/products'
import { useFormatDate } from '@/composables/useFormatDate'

const route = useRoute()
const productStore = useProductStore()

const product = ref(null)
const loading = ref(true)

const { formatDateTime } = useFormatDate()

async function fetchProduct(id) {
  loading.value = true
  try {
    product.value = await productStore.fetchProductById(id)
  } finally {
    loading.value = false
  }
}

watch(
  () => route.params.id,
  (newId) => {
    if (newId) fetchProduct(newId)
  },
)

onMounted(() => {
  fetchProduct(route.params.id)
})
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;

.product-detail-card {
  border-radius: $border-radius-md;
}
</style>
