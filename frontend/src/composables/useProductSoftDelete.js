import { ref } from 'vue'
import api from '@/services/api'
import { useToast } from '@/composables/useToast'
import { parseErrorResponse } from '@/utils/errorMessages'

export function useProductSoftDelete(loadProducts) {
  const { showToast } = useToast()

  const showDeletedProductsDialog = ref(false)
  const deletedProducts = ref([])
  const restoringProductId = ref(null)
  const purgingProductId = ref(null)
  const purgingAllProducts = ref(false)

  async function loadDeletedProducts() {
    try {
      const response = await api.products.getDeletedProducts()
      deletedProducts.value = response.data || []
    } catch (error) {
      showToast({ message: `Could not load the trash: ${parseErrorResponse(error).message}`, type: 'error' })
    }
  }

  async function restoreProduct(productId) {
    if (restoringProductId.value) return

    const product = deletedProducts.value.find((p) => p.id === productId)
    restoringProductId.value = productId
    try {
      await api.products.restoreProduct(productId)

      showToast({
        message: `${product?.name || 'Product'} restored successfully`,
        type: 'success',
      })

      await loadProducts()
      await loadDeletedProducts()

      if (deletedProducts.value.length === 0) {
        showDeletedProductsDialog.value = false
      }
    } catch (error) {
      console.error('Failed to restore product:', error)
      showToast({
        message: 'Failed to restore product. Try again or refresh the page.',
        type: 'error',
      })
    } finally {
      restoringProductId.value = null
    }
  }

  async function purgeDeletedProduct(productId) {
    if (purgingProductId.value) return

    const product = deletedProducts.value.find((p) => p.id === productId)
    purgingProductId.value = productId
    try {
      await api.products.purge(productId)

      showToast({
        message: `${product?.name || 'Product'} permanently deleted.`,
        type: 'warning',
      })

      await loadProducts()
      await loadDeletedProducts()

      if (deletedProducts.value.length === 0) {
        showDeletedProductsDialog.value = false
      }
    } catch (error) {
      console.error('Failed to purge product:', error)
      showToast({
        message: 'Failed to permanently delete product. Try again or refresh the page.',
        type: 'error',
      })
    } finally {
      purgingProductId.value = null
    }
  }

  async function purgeAllDeletedProducts() {
    if (purgingAllProducts.value) return

    purgingAllProducts.value = true
    try {
      const ids = deletedProducts.value.map((p) => p.id)
      for (const id of ids) {
        await api.products.purge(id)
      }

      showToast({
        message: `${ids.length} product(s) permanently deleted.`,
        type: 'warning',
      })

      await loadProducts()
      await loadDeletedProducts()
      showDeletedProductsDialog.value = false
    } catch (error) {
      console.error('Failed to purge all products:', error)
      showToast({
        message: 'Failed to delete all products. Try again or refresh the page.',
        type: 'error',
      })
    } finally {
      purgingAllProducts.value = false
    }
  }

  return {
    showDeletedProductsDialog,
    deletedProducts,
    restoringProductId,
    purgingProductId,
    purgingAllProducts,
    loadDeletedProducts,
    restoreProduct,
    purgeDeletedProduct,
    purgeAllDeletedProducts,
  }
}
