<template>
  <v-container>
    <!-- Header (matches Tasks/Projects pattern) -->
    <v-row class="align-center mb-4 main-window-reveal main-window-reveal--hero main-window-delay-1">
      <v-col>
        <h1 class="text-headline-large">Products</h1>
        <p class="text-body-medium text-muted-a11y mt-1">
          Manage your product configurations and AI agent workspaces.
          <v-tooltip location="bottom start" max-width="480">
            <template #activator="{ props }">
              <v-icon v-bind="props" size="16" class="help-icon">mdi-help-circle-outline</v-icon>
            </template>
            <div>
              <div class="font-weight-bold mb-2">Product Hierarchy</div>
              <div class="mb-2">Products sit at the top of the workflow: <strong>Product → Projects → Jobs → Agents</strong>.</div>
              <div class="mb-2">Each product defines a scope of work. Projects break it into deliverables, jobs assign agents, and agents execute.</div>
              <div>Products can be created manually or your coding agent can analyze a vision document and propose the product architecture during the product creation process.</div>
            </div>
          </v-tooltip>
        </p>
      </v-col>
    </v-row>

    <!-- Filter Bar -->
    <div class="filter-bar main-window-reveal main-window-delay-2">
        <v-text-field
          v-model="search"
          prepend-inner-icon="mdi-magnify"
          placeholder="Search products..."
          variant="solo"
          density="compact"
          clearable
          hide-details
          flat
          aria-label="Search products by name"
          class="filter-search"
          data-testid="products-search"
        />
        <v-select
          v-model="sortBy"
          :items="sortOptions"
          item-title="label"
          item-value="value"
          prepend-inner-icon="mdi-sort"
          placeholder="Sort by"
          variant="solo"
          flat
          density="compact"
          hide-details
          class="filter-select"
          data-testid="products-sort"
        />
        <v-btn color="primary" prepend-icon="mdi-plus" data-testid="products-new" @click="openNewProductDialog">
          New Product
        </v-btn>
        <v-btn
          variant="outlined"
          :color="deletedProductsCount > 0 ? 'warning' : 'grey'"
          prepend-icon="mdi-delete-restore"
          :disabled="deletedProductsCount === 0"
          data-testid="products-deleted-open"
          @click="showDeletedProductsDialog = true"
        >
          Deleted ({{ deletedProductsCount }})
        </v-btn>
      </div>

      <!-- Product Cards (floating, no wrapper card) -->
              <v-row v-if="loading" class="main-window-reveal main-window-delay-3">
                <v-col cols="12" class="text-center py-8">
                  <v-progress-circular indeterminate color="primary"></v-progress-circular>
                  <div class="text-muted-a11y mt-4">Loading products...</div>
                </v-col>
              </v-row>

              <v-row v-else-if="filteredProducts.length === 0" class="main-window-reveal main-window-delay-3">
                <v-col cols="12" class="text-center py-8">
                  <v-icon size="64" color="grey-lighten-2">mdi-package-variant-remove</v-icon>
                  <div class="text-title-large product-text-secondary mt-4">No products found</div>
                  <div class="text-body-medium text-muted-a11y">
                    {{
                      search
                        ? 'Try adjusting your search'
                        : 'Create your first product to get started'
                    }}
                  </div>
                </v-col>
              </v-row>

              <v-row v-else class="main-window-reveal main-window-delay-3">
                <v-col
                  v-for="product in filteredProducts"
                  :key="product.id"
                  cols="12"
                  sm="6"
                  md="4"
                  lg="3"
                >
                  <ProductCard
                    :product="product"
                    :is-active="isProductActive(product)"
                    @info="showProductDetails"
                    @tune="showProductTuning"
                    @toggle-activation="toggleProductActivation"
                    @edit="editProduct"
                    @delete="confirmDelete"
                  />
                </v-col>
              </v-row>

    <!-- Extracted Component Dialogs -->

    <!-- Create/Edit Product Dialog -->
    <ProductForm
      v-model="showDialog"
      v-model:saving="savingProduct"
      :product="editingProduct"
      :is-edit="!!editingProduct && !autoSavedForAnalysis"
      :existing-vision-documents="existingVisionDocuments"
      :uploading-vision="uploadingVision"
      :upload-progress="uploadProgress"
      :vision-upload-error="visionUploadError"
      @save="saveProduct"
      @upload-vision-files="uploadVisionFilesOnAttach"
      @cancel="closeDialog"
      @remove-vision="removeVisionDocument"
      @clear-upload-error="visionUploadError = null"
    />

    <!-- Duplicate-name Modal — blocks the user with an actionable message
         when the backend rejects a product create due to an active duplicate.
         The ProductForm dialog underneath stays open so all typed-in fields
         are preserved; user dismisses, renames, retries. -->
    <v-dialog v-model="showDuplicateNameModal" max-width="480" persistent>
      <v-card class="smooth-border">
        <div class="dlg-header dlg-header--warning">
          <v-icon class="dlg-icon">mdi-alert-circle-outline</v-icon>
          <span class="dlg-title">Duplicate product name</span>
          <v-btn icon variant="text" class="dlg-close" aria-label="Close" @click="showDuplicateNameModal = false">
            <v-icon>mdi-close</v-icon>
          </v-btn>
        </div>
        <v-card-text>{{ duplicateNameMessage }}</v-card-text>
        <div class="dlg-footer">
          <v-spacer />
          <v-btn color="primary" variant="flat" @click="showDuplicateNameModal = false">
            OK
          </v-btn>
        </div>
      </v-card>
    </v-dialog>

    <!-- Product Details Dialog -->
    <ProductDetailsDialog
      v-model="showDetailsDialog"
      :product="selectedProduct"
      :vision-documents="detailsVisionDocuments"
      :stats="productStats"
      @refresh-product="handleProductRefresh"
    />

    <ProductTuningDialog
      v-model="showTuningDialog"
      :product="tuningProduct"
      @refresh-product="handleProductRefresh"
    />

    <!-- Delete Confirmation Dialog -->
    <ProductDeleteDialog
      v-model="showDeleteDialog"
      :product="deletingProduct"
      :cascade-impact="cascadeImpact"
      :loading="loadingCascadeImpact"
      :deleting="deleting"
      @confirm="confirmDeleteProduct"
      @cancel="cancelDelete"
    />

    <!-- Deleted Products Recovery Dialog -->
    <DeletedProductsRecoveryDialog
      v-model="showDeletedProductsDialog"
      :deleted-products="deletedProducts"
      :restoring-product-id="restoringProductId"
      :purging-product-id="purgingProductId"
      :purging-all="purgingAllProducts"
      @restore="restoreProduct"
      @purge="purgeDeletedProduct"
      @purge-all="purgeAllDeletedProducts"
    />

    <!-- Handover 0050: Activation Warning Dialog -->
    <ActivationWarningDialog
      v-model="showActivationWarning"
      :new-product="pendingActivation || {}"
      :current-active="currentActiveProduct || {}"
      @confirm="confirmActivation"
      @cancel="cancelActivation"
    />
  </v-container>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProductStore } from '@/stores/products'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'
import { useProductActivation } from '@/composables/useProductActivation'
import { useProductSoftDelete } from '@/composables/useProductSoftDelete'
import { useProductVisionUpload } from '@/composables/useProductVisionUpload'
import api from '@/services/api'
import { parseErrorResponse } from '@/utils/errorMessages'
import ActivationWarningDialog from '@/components/products/ActivationWarningDialog.vue'
import ProductDeleteDialog from '@/components/products/ProductDeleteDialog.vue'
import ProductDetailsDialog from '@/components/products/ProductDetailsDialog.vue'
import ProductTuningDialog from '@/components/products/ProductTuningDialog.vue'
import DeletedProductsRecoveryDialog from '@/components/products/DeletedProductsRecoveryDialog.vue'
import ProductForm from '@/components/products/ProductForm.vue'
import ProductCard from '@/components/products/ProductCard.vue'

const route = useRoute()
const router = useRouter()
const productStore = useProductStore()
const settingsStore = useSettingsStore()
const { showToast } = useToast()
// State
const loading = ref(false)
const search = ref('')
const sortBy = ref('name')
const showDialog = ref(false)
const showDeleteDialog = ref(false)
const showDetailsDialog = ref(false)
const showTuningDialog = ref(false)
const editingProduct = ref(null)
const deletingProduct = ref(null)
const selectedProduct = ref(null)
const tuningProduct = ref(null)
const deleting = ref(false)
const autoSavedForAnalysis = ref(null) // Holds product ID if auto-saved for stage-analysis, null otherwise
// Owned here (not inside ProductForm) so we can reset the spinner from
// the saveProduct() catch block when the backend rejects (e.g. duplicate
// active-product name). Two-way bound via v-model:saving on <ProductForm>.
const savingProduct = ref(false)
// Duplicate-name modal — used instead of a toast for active-product name
// collisions because the form stays open behind it and the user must
// pick a different name (blocking decision, not a passive notification).
const showDuplicateNameModal = ref(false)
const duplicateNameMessage = ref('')
const detailsVisionDocuments = ref([])
const cascadeImpact = ref(null)
const loadingCascadeImpact = ref(false)

// Upload composable — manages vision file upload state and upload flow.
// editingProduct and autoSavedForAnalysis are passed by reference so the
// composable's auto-create path can mutate the view's product identity.
const {
  uploadingVision,
  uploadProgress,
  visionUploadError,
  existingVisionDocuments,
  loadExistingVisionDocuments,
  uploadVisionFilesOnAttach,
  resetUploadState,
} = useProductVisionUpload({ editingProduct, autoSavedForAnalysis })

const {
  showActivationWarning,
  pendingActivation,
  currentActiveProduct,
  toggleProductActivation,
  confirmActivation,
  cancelActivation,
} = useProductActivation(() => loadProducts())

const {
  showDeletedProductsDialog,
  deletedProducts,
  restoringProductId,
  purgingProductId,
  purgingAllProducts,
  loadDeletedProducts,
  restoreProduct,
  purgeDeletedProduct,
  purgeAllDeletedProducts,
} = useProductSoftDelete(() => loadProducts())

// Sort options
const sortOptions = [
  { label: 'Name (A-Z)', value: 'name' },
  { label: 'Date Created (Newest)', value: 'date-newest' },
  { label: 'Date Created (Oldest)', value: 'date-oldest' },
]

// Computed
const filteredProducts = computed(() => {
  // Filter by search
  let products = productStore.products
  if (search.value) {
    const searchLower = search.value.toLowerCase()
    products = products.filter(
      (product) =>
        product.name.toLowerCase().includes(searchLower) ||
        product.description?.toLowerCase().includes(searchLower),
    )
  }

  // Sort products - ACTIVE PRODUCTS FIRST (leftmost/top)
  const sorted = [...products]

  // Primary sort: Active products first
  sorted.sort((a, b) => {
    // If one is active and the other isn't, active comes first
    // Use isProductActive for single source of truth (Handover 0320)
    const aActive = isProductActive(a)
    const bActive = isProductActive(b)
    if (aActive && !bActive) return -1
    if (!aActive && bActive) return 1

    // Both active or both inactive - apply secondary sort
    switch (sortBy.value) {
      case 'name':
        return a.name.localeCompare(b.name)
      case 'date-newest':
        return new Date(b.created_at) - new Date(a.created_at)
      case 'date-oldest':
        return new Date(a.created_at) - new Date(b.created_at)
      default:
        return 0
    }
  })

  return sorted
})

const deletedProductsCount = computed(() => {
  return deletedProducts.value.length
})

// Product stats for details dialog
const productStats = computed(() => {
  if (!selectedProduct.value) {
    return {
      unresolved_tasks: 0,
      unfinished_projects: 0,
    }
  }
  return {
    unresolved_tasks: selectedProduct.value.unresolved_tasks || 0,
    unfinished_projects: selectedProduct.value.unfinished_projects || 0,
  }
})

// Methods — Handover 0320: Single source of truth — uses activeProduct.id not product.is_active
function isProductActive(product) {
  return productStore.activeProduct?.id === product.id
}

// Handover 0320: Handler for ProductForm remove-vision event (delete existing document)
async function removeVisionDocument(doc) {
  try {
    await api.visionDocuments.delete(doc.id)

    // Remove from existing documents list
    const index = existingVisionDocuments.value.findIndex((d) => d.id === doc.id)
    if (index > -1) {
      existingVisionDocuments.value.splice(index, 1)
    }

    showToast({
      message: `Deleted vision document: ${doc.document_name}`,
      type: 'success',
      timeout: 3000,
    })
  } catch (error) {
    console.error('Failed to delete vision document:', error)
    showToast({
      message: 'Failed to delete vision document. Try again or refresh the page.',
      type: 'error',
      timeout: 5000,
    })
  }
}

async function showProductDetails(product) {
  // BE-6066 P4: Details renders tech_stack / architecture / test_config, which
  // the lean list object no longer carries — fetch the full product on open.
  // Both fetches key off product.id, so they run in PARALLEL: detail-on-click
  // must not cost more round-trip latency than the one fetch this dialog
  // already paid pre-P4.
  const [full, visionResult] = await Promise.all([
    productStore.fetchProductById(product.id),
    api.visionDocuments.listByProduct(product.id).catch((error) => {
      console.error('Failed to load vision documents:', error)
      return null
    }),
  ])
  if (!full) {
    showToast({
      message: 'Could not load full product details. Refresh and retry.',
      type: 'error',
      timeout: 5000,
    })
  }
  selectedProduct.value = full || product
  detailsVisionDocuments.value = visionResult?.data || []

  showDetailsDialog.value = true
}

async function showProductTuning(product) {
  tuningProduct.value = product
  showTuningDialog.value = true
}

async function handleProductRefresh() {
  await loadProducts()

  if (selectedProduct.value) {
    // BE-6066 P4: productStore.products is now LEAN — re-syncing from it would
    // strip the detail relations the Details dialog renders. Re-fetch the full
    // product instead.
    const full = await productStore.fetchProductById(selectedProduct.value.id)
    selectedProduct.value = full || selectedProduct.value
    // FE-6138: also refresh the active vision-docs list so a just-restored
    // document re-appears without closing/reopening the Details dialog.
    const visionResult = await api.visionDocuments
      .listByProduct(selectedProduct.value.id)
      .catch(() => null)
    if (visionResult) detailsVisionDocuments.value = visionResult.data || []
  }

  if (tuningProduct.value) {
    tuningProduct.value = productStore.products.find((product) => product.id === tuningProduct.value.id) || tuningProduct.value
  }
}

function openNewProductDialog() {
  editingProduct.value = null
  showDialog.value = true
}

async function editProduct(product) {
  // BE-6066 P4: the list object is now lean (no tech_stack / architecture /
  // test_config — those load on demand). Fetch the full product so ProductForm
  // receives the detail fields it edits. Fall back to the lean object on failure
  // so Edit still opens (degraded) with a heads-up.
  // Both fetches key off product.id, so they run in PARALLEL: Edit-open already
  // paid the vision-docs round trip pre-P4; the detail fetch must not add a
  // second serial one.
  const [full] = await Promise.all([
    productStore.fetchProductById(product.id),
    loadExistingVisionDocuments(product.id),
  ])
  if (!full) {
    showToast({
      message: 'Could not load full product details. Some fields may be empty — refresh and retry.',
      type: 'error',
      timeout: 5000,
    })
  }
  editingProduct.value = full || product

  showDialog.value = true
}

async function confirmDelete(product) {
  deletingProduct.value = product
  // Drop the previous product's impact before the dialog can paint. The dialog
  // opens before the fetch resolves, and the close paths (successful delete,
  // 404 cleanup) do not reset this — so without the clear here, a failed fetch
  // leaves the last product's counts on screen under THIS product's name.
  // Clearing at the single entry point keeps that invariant true for any future
  // exit path too.
  cascadeImpact.value = null
  showDeleteDialog.value = true

  // Fetch cascade impact
  loadingCascadeImpact.value = true
  try {
    const response = await api.products.getCascadeImpact(product.id)
    cascadeImpact.value = response.data
  } catch (error) {
    if (error?.response?.status === 404) {
      // Product already gone from DB — let user confirm removal of ghost card
      cascadeImpact.value = null
    } else {
      console.error('Failed to get cascade impact:', error)
      showToast({
        message: 'Failed to load deletion impact. Refresh the page and try again.',
        type: 'error',
        timeout: 5000,
      })
    }
  } finally {
    loadingCascadeImpact.value = false
  }
}

async function saveProduct(payload) {
  const { productData } = payload

  try {
    // Create or update — vision files already uploaded on attach
    if (editingProduct.value) {
      await productStore.updateProduct(editingProduct.value.id, productData)
    } else {
      await productStore.createProduct(productData)
    }

    // Product is now permanent — clear auto-save cleanup flag
    autoSavedForAnalysis.value = null

    // Refresh products
    await loadProducts()

    // Close dialog
    showDialog.value = false

    const wasCreating = !editingProduct.value
    showToast({
      message: wasCreating
        ? 'Product created — activate it with the play button to start using it'
        : 'Product updated successfully',
      type: 'success',
      timeout: wasCreating ? 6000 : 3000,
    })

    // Reset state
    editingProduct.value = null
    resetUploadState()
  } catch (error) {
    console.error('Failed to save product:', error)
    // Surface the real backend message instead of a generic
    // "check your connection" toast. The server returns a structured
    // {error_code, message} payload (e.g. duplicate active-product name)
    // that the user needs verbatim to know what to fix.
    const parsed = parseErrorResponse(error)
    const isDuplicateName =
      parsed?.message && /already exists/i.test(parsed.message)
    if (isDuplicateName) {
      // Modal beats a toast for blocking errors that require user action,
      // and avoids any visual confusion with the WebSocket-driven toast
      // surface. Form stays open behind the modal with all fields intact.
      duplicateNameMessage.value = `${parsed.message}. Pick a different name, or activate or rename the existing product.`
      showDuplicateNameModal.value = true
    } else {
      showToast({
        message: parsed?.message || 'Failed to save product. Check your connection and try again.',
        type: 'error',
        timeout: 5000,
      })
    }
  } finally {
    // Reset the save-button spinner whether the call succeeded or failed.
    // Without this, a 4xx left the button stuck in :loading state and the
    // UI looked frozen / "backend locked up".
    savingProduct.value = false
  }
}

async function confirmDeleteProduct() {
  deleting.value = true
  try {
    await productStore.deleteProduct(deletingProduct.value.id)

    // If was active product, clear active state
    if (productStore.currentProductId === deletingProduct.value.id) {
      productStore.currentProductId = null
      productStore.currentProduct = null
      localStorage.removeItem('currentProductId')
    }

    // Close dialog
    showDeleteDialog.value = false
    const productName = deletingProduct.value.name
    deletingProduct.value = null

    // Refresh products (includes deleted products list)
    await loadProducts()

    // Show success message
    showToast({
      message: `${productName} moved to trash. Recoverable for 10 days.`,
      type: 'info',
      timeout: 4000,
    })
  } catch (error) {
    if (error?.response?.status === 404) {
      // Product already gone from DB (orphan card) — clean up UI
      showDeleteDialog.value = false
      const productName = deletingProduct.value?.name || 'Product'
      deletingProduct.value = null
      await loadProducts()
      showToast({ message: `${productName} was already removed.`, type: 'info', timeout: 3000 })
    } else {
      console.error('Failed to delete product:', error)
      showToast({
        message: 'Failed to move product to trash. Try again or refresh the page.',
        type: 'error',
        timeout: 5000,
      })
    }
  } finally {
    deleting.value = false
  }
}

function cancelDelete() {
  showDeleteDialog.value = false
  deletingProduct.value = null
  cascadeImpact.value = null
}

async function closeDialog() {
  // Clean up auto-saved product if user never did a real save (404 = already gone, ignore)
  if (autoSavedForAnalysis.value) {
    try {
      await productStore.deleteProduct(autoSavedForAnalysis.value)
    } catch {
      // Silently ignore — product may already be deleted
    }
    autoSavedForAnalysis.value = null
  }

  showDialog.value = false
  editingProduct.value = null
  resetUploadState()

  // Refresh product list on close
  loadProducts()
}

async function loadProducts() {
  loading.value = true
  try {
    await productStore.fetchProducts()
    await loadDeletedProducts()
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  // FE-9200: the onboarding tutorial's "I'll fill it in myself" door lands
  // here with ?create=true — open the classic ProductForm straight away
  // (same idiom as WelcomeView's openSetup/openGuide query triggers).
  // Optional chaining: component tests mount this view without a router.
  if (route?.query?.create === 'true') {
    openNewProductDialog()
    router?.replace({ path: route.path })
  }

  // FE-9222: the context-tuning banner deep-links here with ?tune=<product_id>
  // to open the tuning dialog for that product. Captured before loadProducts so
  // a concurrent ?create strip cannot swallow it; the lookup runs after the list
  // loads, and an unknown/missing id fails soft (no dialog, param still stripped).
  const tuneProductId = route?.query?.tune

  await loadProducts()

  if (tuneProductId) {
    const target = productStore.products.find((product) => product.id === tuneProductId)
    if (target) showProductTuning(target)
    router?.replace({ path: route.path })
  }
  // Load field toggle configuration (Handover 0049, 0820)
  try {
    await settingsStore.fetchFieldToggleConfig()
  } catch {
    // Field toggle config not available
  }
})
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;
@use '../styles/list-filter-bar' as filterBar;

@include filterBar.list-filter-bar;

.filter-select {
  flex: 0 0 auto;
  min-width: 200px;
}

/* Empty-state secondary text */
.product-text-secondary {
  color: var(--text-secondary) !important; /* !important: override Vuetify text color classes on same element */
}
</style>
